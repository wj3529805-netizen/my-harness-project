"""Reproduce A11/A14 using the local MCP SDK client and synthetic mock data.

Run from the repository root with its venv, choosing a new evidence file:
  .venv/bin/python evidence/mac-acceptance/check_mcp_boundary.py --out /tmp/mcp-boundary.json

This starts the real CETACEA stdio server in a subprocess. It does not connect
Lightroom, approve tasks, or represent an actual Codex/Claude/Harness client.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from cetacea import db
from cetacea.core import Workbench


EXPECTED_TOOLS = {
    'photo_list_orders', 'photo_list_sources', 'photo_scan_source',
    'photo_plan_import', 'photo_execute_import', 'photo_get_task',
    'photo_cancel_task', 'photo_retry_task', 'photo_list_assets',
    'lightroom_get_status', 'lightroom_import_verified',
    'lightroom_apply_preset', 'lightroom_export_preview', 'photo_verify_preview',
}
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']


def source_snapshot(source):
    return {str(path.relative_to(source)): {
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'mtime_ns': path.stat().st_mtime_ns,
    } for path in source.rglob('*') if path.is_file()}


async def scenario(root):
    home, library, preview, card = [root / name for name in ('home', 'library', 'preview', 'card')]
    card.mkdir()
    (card / 'synthetic.RAF').write_bytes(b'CETACEA-MOCK synthetic source; not a decodable RAW\n')
    (card / 'existing.XMP').write_bytes(b'CETACEA-MOCK sidecar; preserve exactly\n')
    before = source_snapshot(card)
    w = Workbench.init(home, library, preview)
    w.add_source('test-card', card)
    w.create_order('test-order', 'Synthetic MCP boundary acceptance')
    w.add_photographer('test-photographer', 'Synthetic fixture')
    w.add_preset('test-preset', 'MOCK test preset')
    assert w.adapter.mock is True
    args = ['-m', 'cetacea.cli', '--home', str(home), 'mcp-serve', '--actor', 'ai:acceptance-sdk']
    calls = []

    async def invoke(session, tool, arguments=None):
        result = await asyncio.wait_for(session.call_tool(tool, arguments or {}), 15)
        raw = result.model_dump(mode='json', exclude_none=True)
        calls.append({'tool': tool, 'arguments': arguments or {}, 'response': raw})
        payload = result.structured_content
        if payload is None and result.content and result.content[0].type == 'text':
            try:
                payload = json.loads(result.content[0].text)
            except json.JSONDecodeError:
                payload = None
        return result, payload

    async with stdio_client(StdioServerParameters(command=sys.executable, args=args)) as streams:
        async with ClientSession(*streams) as session:
            initialized = await asyncio.wait_for(session.initialize(), 15)
            listing = await asyncio.wait_for(session.list_tools(), 15)
            actual = {tool.name for tool in listing.tools}
            assert actual == EXPECTED_TOOLS, actual
            for tool in listing.tools:
                schema = json.dumps(tool.input_schema).lower()
                for forbidden in ('path', 'shell', 'delete', 'approve'):
                    assert forbidden not in tool.name.lower()
                    assert forbidden not in schema
                assert not any('exec' in key for key in tool.input_schema.get('properties', {}))

            result, status = await invoke(session, 'lightroom_get_status')
            assert not result.is_error and status['mock'] is True and 'MOCK' in status['status']
            result, plan = await invoke(session, 'photo_plan_import', {
                'order_id': 'test-order', 'photographer_id': 'test-photographer',
                'source_id': 'test-card', 'preset_id': 'test-preset', 'stages': STAGES,
            })
            assert not result.is_error and plan['state'] == 'WAITING_APPROVAL'
            task_id = plan['task_id']
            for tool in ('photo_execute_import', 'lightroom_import_verified', 'lightroom_export_preview'):
                result, payload = await invoke(session, tool, {'task_id': task_id})
                assert result.is_error and payload['code'] == 'NOT_APPROVED'
            result, payload = await invoke(session, 'lightroom_apply_preset', {
                'task_id': task_id, 'preset_id': 'test-preset',
            })
            assert result.is_error and payload['code'] == 'NOT_APPROVED'

            for tool in ('approve', 'shell', 'delete_file', 'read_file'):
                result, _ = await invoke(session, tool)
                assert result.is_error, tool
            for tool, arguments in (
                ('photo_scan_source', {'source_id': '../outside'}),
                ('photo_get_task', {'task_id': '../../outside'}),
            ):
                result, payload = await invoke(session, tool, arguments)
                assert result.is_error and payload['code'] == 'INVALID_ARGUMENT'

            result, final_task = await invoke(session, 'photo_get_task', {'task_id': task_id})
            assert not result.is_error and final_task['state'] == 'WAITING_APPROVAL'

    library_files = [str(path.relative_to(library)) for path in library.rglob('*') if path.is_file()]
    preview_files = [str(path.relative_to(preview)) for path in preview.rglob('*') if path.is_file()]
    assert library_files == [] and preview_files == []
    after = source_snapshot(card)
    assert before == after
    with db.connect(home) as conn:
        approvals = conn.execute('SELECT COUNT(*) FROM approvals').fetchone()[0]
        audit = [dict(row) for row in conn.execute('SELECT * FROM audit_log ORDER BY rowid')]
        task_state = conn.execute('SELECT state FROM tasks WHERE task_id=?', (task_id,)).fetchone()[0]
    assert approvals == 0 and task_state == 'WAITING_APPROVAL'
    ai_events = [row for row in audit if row['actor'] == 'ai:ai:acceptance-sdk']
    assert ai_events and any(row['action'] == 'execute' for row in ai_events)
    return {
        'result': 'PASS',
        'marker': 'CETACEA-MOCK; local macOS SDK-to-stdio boundary acceptance',
        'scope': {
            'A11': 'PASS: AI has no approval tool; unapproved execution denied without library outputs',
            'A14': 'PASS for local MCP SDK stdio client; actual Codex/Claude/Harness client NOT_RUN',
            'real_lightroom': 'NOT_RUN', 'production_data': 'NOT_USED',
            'source_data': 'synthetic bytes and sidecar; not a decodable RAW',
        },
        'runtime': {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(), 'machine': platform.machine()},
        'stdio': {'command': sys.executable, 'args': args, 'initialize': initialized.model_dump(mode='json', exclude_none=True)},
        'tools': [tool.model_dump(mode='json', exclude_none=True) for tool in listing.tools],
        'checks': {
            'tool_count': len(actual), 'exact_14_tool_whitelist': actual == EXPECTED_TOOLS,
            'no_path_shell_delete_approve_inputs': True,
            'unknown_approval_and_arbitrary_tools_rejected': True,
            'traversal_ids_rejected': True, 'unapproved_execution_code': 'NOT_APPROVED',
            'library_files': library_files, 'preview_files': preview_files,
            'approval_rows': approvals, 'task_state': task_state, 'source_unchanged': before == after,
            'ai_audit_event_count': len(ai_events),
        },
        'source_before': before, 'source_after': after, 'calls': calls, 'audit': audit,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New JSON evidence file; existing files are never overwritten')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new --out path; evidence is not overwritten')
    with tempfile.TemporaryDirectory(prefix='cetacea-mcp-boundary-') as temporary:
        result = asyncio.run(asyncio.wait_for(scenario(Path(temporary)), 90))
    result['temporary_mock_workspace_removed'] = True
    result['recorded_at_utc'] = datetime.now(timezone.utc).isoformat()
    with args.out.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print(json.dumps({'result': result['result'], 'evidence': str(args.out.resolve()), 'checks': result['checks']}, indent=2))


if __name__ == '__main__':
    main()
