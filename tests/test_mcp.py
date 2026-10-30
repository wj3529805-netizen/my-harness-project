"""Gate 2 uses actual local stdio processes, never a mocked MCP transport."""
import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
import pytest
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from cetacea import db
from cetacea.core import Workbench
from cetacea.perms import ai_principal, PermissionDenied

TOOLS = {'photo_list_orders', 'photo_list_sources', 'photo_scan_source', 'photo_plan_import', 'photo_execute_import', 'photo_get_task', 'photo_cancel_task', 'photo_retry_task', 'photo_list_assets', 'lightroom_get_status', 'lightroom_import_verified', 'lightroom_apply_preset', 'lightroom_export_preview', 'photo_verify_preview'}
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']

@asynccontextmanager
async def client(home, scopes=None):
    args = ['-m', 'cetacea.cli', '--home', str(home), 'mcp-serve']
    if scopes is not None: args += ['--scopes', scopes]
    async with stdio_client(StdioServerParameters(command=sys.executable, args=args)) as streams:
        async with ClientSession(*streams) as session:
            await asyncio.wait_for(session.initialize(), 30)
            yield session

async def call(session, name, args=None, error=None):
    result = await asyncio.wait_for(session.call_tool(name, args or {}), 30)
    assert result.is_error == bool(error), result
    data = result.structured_content or json.loads(result.content[0].text)
    if error: assert data['code'] == error
    return data

def run(coro): return asyncio.run(asyncio.wait_for(coro, 30))

def cli(w, *args):
    result = subprocess.run([sys.executable, '-m', 'cetacea.cli', '--home', str(w.home), '--json', *args], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)

def test_mcp_tool_surface(env):
    w, card = env
    async def scenario():
        async with client(w.home) as s:
            listing = await asyncio.wait_for(s.list_tools(), 30)
            assert {t.name for t in listing.tools} == TOOLS
            for t in listing.tools:
                for word in ['path', 'shell', 'delete', 'approve']:
                    assert word not in t.name
                    assert word not in json.dumps(t.input_schema).lower()
                assert not any('exec' in key for key in t.input_schema.get('properties', {}))
    run(scenario())

def test_15_shared_state_idempotent_mcp(env):
    w, card = env
    (card/'one.RAF').write_bytes(b'raw one')
    (card/'one.JPG').write_bytes(b'jpg one')
    w.add_preset('preset', 'MOCK preset')
    request = dict(order_id='order', photographer_id='p', source_id='card', preset_id='preset', stages=STAGES)
    async def scenario():
        async with client(w.home) as s:
            first = await call(s, 'photo_plan_import', request)
            tid = first['task_id']
            for _ in range(3):
                assert await call(s, 'photo_plan_import', request) == first
            assert cli(w, 'task', 'show', tid)['task_id'] == tid
            cli(w, 'approve', tid, first['plan_digest'])
            completed = await call(s, 'photo_execute_import', {'task_id': tid})
            assert completed['state'] == 'COMPLETED' and completed['mock'] is True
            before = {str(p): (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for root in ['library_root', 'preview_root'] for p in Path(w.config[root]).rglob('*') if p.is_file()}
            for _ in range(3):
                assert await call(s, 'photo_execute_import', {'task_id': tid}) == completed
                assert await call(s, 'lightroom_import_verified', {'task_id': tid}) == completed
                assert await call(s, 'lightroom_apply_preset', {'task_id': tid, 'preset_id': 'preset'}) == completed
                assert await call(s, 'lightroom_export_preview', {'task_id': tid}) == completed
            assert all((Path(p).stat().st_ino, Path(p).stat().st_mtime_ns, Path(p).read_bytes()) == value for p, value in before.items())
            assert cli(w, 'task', 'show', tid)['state'] == 'COMPLETED'
            assert len(cli(w, 'assets', '--task-id', tid)) == 2
            with db.connect(w.home) as c:
                assert c.execute('SELECT COUNT(*) FROM assets').fetchone()[0] == 2
                assert c.execute('SELECT COUNT(*) FROM assets WHERE lr_photo_id IS NOT NULL').fetchone()[0] == 1
                assert c.execute('SELECT COUNT(*) FROM previews').fetchone()[0] == 1
                assert c.execute('SELECT COUNT(*) FROM task_steps').fetchone()[0] == 5
                assert {r[0].split(':')[0] for r in c.execute('SELECT DISTINCT actor FROM audit_log')} == {'human', 'ai'}
            other = w.plan_import('order', 'p', 'card', batch_label='cancel')
            assert (await call(s, 'photo_get_task', {'task_id': other['task_id']}))['state'] == 'WAITING_APPROVAL'
            cli(w, 'cancel', other['task_id'])
            assert (await call(s, 'photo_get_task', {'task_id': other['task_id']}))['state'] == 'CANCELLED'
    run(scenario())

def test_16_mcp_denials(env):
    w, card = env
    (card/'one.RAF').write_bytes(b'raw')
    t = w.plan_import('order', 'p', 'card', stages=STAGES)
    async def scenario():
        async with client(w.home) as s:
            for tool in ['photo_execute_import', 'lightroom_import_verified', 'lightroom_export_preview']:
                await call(s, tool, {'task_id': t['task_id']}, 'NOT_APPROVED')
            await call(s, 'photo_get_task', {'task_id': '../../etc'}, 'INVALID_ARGUMENT')
            await call(s, 'photo_execute_import', {'task_id': 'missing'}, 'NOT_FOUND')
            await call(s, 'photo_scan_source', {'source_id': 'missing'}, 'NOT_FOUND')
            result = await asyncio.wait_for(s.call_tool('approve', {'task_id': t['task_id']}), 30)
            assert result.is_error
            result = await asyncio.wait_for(s.call_tool('photo_scan_source', {'source_id': 'card', 'path': '../../etc', 'shell': 'touch forbidden'}), 30)
            if not result.is_error:
                data = result.structured_content or json.loads(result.content[0].text)
                assert len(data['files']) == 1 and data['files'][0]['rel_path'] == 'one.RAF'
            w.approve(t['task_id'], t['plan_digest'])
            with db.connect(w.home) as c: c.execute('UPDATE tasks SET plan_digest=? WHERE task_id=?', ('stale', t['task_id']))
            await call(s, 'photo_execute_import', {'task_id': t['task_id']}, 'NOT_APPROVED')
            assert not list(Path(w.config['library_root']).rglob('*'))
        async with client(w.home, 'read') as s:
            await call(s, 'photo_plan_import', dict(order_id='order', photographer_id='p', source_id='card'), 'PERMISSION_DENIED')
    run(scenario())
    for scopes in [{'approve'}, {'admin'}]:
        with pytest.raises(PermissionDenied): ai_principal(scopes=scopes)
    ai = Workbench(w.home, principal=ai_principal())
    with pytest.raises(PermissionDenied): ai.approve(t['task_id'], t['plan_digest'])

def test_mcp_individual_stages_use_approved_runner(env):
    w, card = env
    (card/'one.RAF').write_bytes(b'raw')
    w.add_preset('preset')
    t = w.plan_import('order', 'p', 'card', preset_id='preset', stages=STAGES)
    w.approve(t['task_id'], t['plan_digest'])
    # Ingest through the same runner, leaving remaining approved stages paused.
    assert w.execute(t['task_id'], _stages=['ingest'])['state'] == 'PAUSED'
    async def scenario():
        async with client(w.home) as s:
            for name, extra, state in [('lightroom_import_verified', {}, 'PAUSED'), ('lightroom_apply_preset', {'preset_id': 'preset'}, 'PAUSED'), ('lightroom_export_preview', {}, 'COMPLETED')]:
                args = {'task_id': t['task_id'], **extra}
                result = await call(s, name, args)
                assert result['state'] == state
                for _ in range(3): assert await call(s, name, args) == result
            await call(s, 'lightroom_apply_preset', {'task_id': t['task_id'], 'preset_id': 'unknown'}, 'NOT_FOUND')
            assert (await call(s, 'photo_verify_preview', {'task_id': t['task_id']}))['status'] == 'OK'
    run(scenario())
