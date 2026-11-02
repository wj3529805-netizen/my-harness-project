"""A10: real project stdio MCP repeats against one completed test task.

No approval tools or direct Lightroom tools are called. Snapshots intentionally
exclude other batches/tasks so concurrent independent acceptance work is safe.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'evidence/mac-acceptance'
HOME = ROOT / 'acceptance-data/home'
TASK = json.loads((EVIDENCE / 'cc0-full-result.json').read_text())
CONFIG = json.loads((HOME / 'config.json').read_text())
TID = TASK['task_id']
assert TASK['state'] == 'COMPLETED'
ASSET_IDS = [item['asset_id'] for item in TASK['plan']['files']]
FILE_ROOTS = {
    'library': Path(CONFIG['library_root']) / TASK['plan']['destination'],
    'preview': Path(CONFIG['preview_root']) / TASK['order_id'] / TASK['photographer_id'] / TASK['batch_id'] / TID,
}
REQUEST = dict(order_id='test', photographer_id='tester', source_id='cc0',
               batch_label='publicraw', preset_id='testpreset',
               stages=['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify'])


def db_snapshot():
    with sqlite3.connect(f'file:{HOME / "state.sqlite3"}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        task = dict(conn.execute('SELECT * FROM tasks WHERE task_id=?', (TID,)).fetchone())
        steps = [dict(row) for row in conn.execute('SELECT * FROM task_steps WHERE task_id=? ORDER BY run,stage', (TID,))]
        previews = [dict(row) for row in conn.execute('SELECT * FROM previews WHERE task_id=? ORDER BY preview_id', (TID,))]
        marks = ','.join('?' for _ in ASSET_IDS)
        assets = [dict(row) for row in conn.execute(f'SELECT * FROM assets WHERE asset_id IN ({marks}) ORDER BY asset_id', ASSET_IDS)]
    return {'task': task, 'counts': {'task_steps': len(steps), 'assets': len(assets), 'previews': len(previews)},
            'task_steps': steps, 'assets': assets, 'previews': previews}


def snapshot():
    files = {}
    for label, root in FILE_ROOTS.items():
        assert root.is_dir(), root
        for path in sorted(root.rglob('*')):
            assert not path.is_symlink(), path
            if not path.is_file():
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                stat = os.fstat(stream.fileno())
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                final = os.fstat(stream.fileno())
            assert (stat.st_ino, stat.st_mtime_ns, stat.st_size) == (final.st_ino, final.st_mtime_ns, final.st_size), path
            files[f'{label}/{path.relative_to(root)}'] = {'inode': stat.st_ino, 'mtime_ns': stat.st_mtime_ns, 'size': stat.st_size, 'sha256': sha}
    return {'files': files, 'database': db_snapshot()}


async def main():
    started = datetime.now(timezone.utc).isoformat()
    before = snapshot()
    assert before['database']['task']['state'] == 'COMPLETED'
    calls = []
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'cetacea.cli', '--home', str(HOME), 'mcp-serve'])
    async with stdio_client(params) as streams:
        async with ClientSession(*streams, read_timeout_seconds=30) as session:
            await session.initialize()
            listing = await session.list_tools()
            names = sorted(tool.name for tool in listing.tools)
            assert not any(any(word in name for word in ['approve', 'shell', 'delete']) for name in names)
            for repeat in range(1, 4):
                for name, args in [
                    ('photo_plan_import', REQUEST),
                    ('photo_execute_import', {'task_id': TID}),
                    ('lightroom_import_verified', {'task_id': TID}),
                    ('lightroom_apply_preset', {'task_id': TID, 'preset_id': 'testpreset'}),
                    ('lightroom_export_preview', {'task_id': TID}),
                ]:
                    result = await session.call_tool(name, args)
                    data = result.structured_content or json.loads(result.content[0].text)
                    assert not result.is_error, (name, data)
                    assert data['task_id'] == TID and data['state'] == 'COMPLETED', (name, data)
                    assert data['mock'] is False, (name, data)
                    calls.append({'repeat': repeat, 'tool': name, 'arguments': args,
                                  'task_id': data['task_id'], 'state': data['state'],
                                  'mock': data['mock'], 'run_count': data['run_count']})
    after = snapshot()
    report = {'check': 'A10', 'status': 'PASS' if before == after else 'FAIL',
              'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
              'task_id': TID, 'scope': {key: str(path) for key, path in FILE_ROOTS.items()},
              'calls': calls, 'tool_surface': names, 'before': before, 'after': after,
              'files_unchanged': before['files'] == after['files'],
              'task_database_rows_unchanged': before['database'] == after['database'],
              'limitation': 'Uses the completed real-adapter test task through project stdio MCP. No direct Lightroom catalog query is performed here; catalog inventory is separate evidence. Audit log additions from the read/execute requests are expected and excluded.'}
    (EVIDENCE / 'A10-repeat-mcp-result.json').write_text(json.dumps(report, indent=2))
    assert before == after, 'Scoped file/database snapshots changed; see evidence JSON'
    print(json.dumps({'status': report['status'], 'task_id': TID, 'calls': len(calls),
                      'file_count': len(before['files']), 'counts': before['database']['counts'],
                      'evidence': str(EVIDENCE / 'A10-repeat-mcp-result.json')}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
