import json
from pathlib import Path

import pytest

from cetacea import db
from cetacea.core import Workbench
from cetacea.perms import PermissionDenied, NotApproved, ai_principal
from test_mcp import STAGES, TOOLS, call, client, run


def prepare(env, count=1):
    w, card = env
    for i in range(count):
        (card / f'{i}.RAF').write_bytes(f'raw {i}'.encode())
    w.add_preset('preset', 'MOCK preset')
    t = w.plan_import('order', 'p', 'card', preset_id='preset', stages=STAGES)
    return w, t


def approvals(w):
    with db.connect(w.home) as c:
        return c.execute('SELECT count(*) FROM approvals').fetchone()[0]


def test_mcp_full_pipeline_one_approval(env):
    w, card = env
    (card / 'one.RAF').write_bytes(b'raw')
    w.add_preset('preset', 'MOCK preset')
    args = dict(order_id='order', photographer_id='p', source_id='card', preset_id='preset')
    async def scenario():
        async with client(w.home) as s:
            t = await call(s, 'photo_plan_import', args)
            assert t['state'] == 'WAITING_APPROVAL' and t['plan']['stages'] == STAGES
            assert (await call(s, 'photo_plan_import', args))['task_id'] == t['task_id']
            await call(s, 'photo_execute_import', {'task_id': t['task_id']}, 'NOT_APPROVED')
            with pytest.raises(PermissionDenied):
                Workbench(w.home, principal=ai_principal()).approve(t['task_id'], t['plan_digest'])
            w.approve(t['task_id'], t['plan_digest'])
            assert approvals(w) == 1
            done = await call(s, 'photo_execute_import', {'task_id': t['task_id']})
            assert done['state'] == 'COMPLETED' and done['mock'] is True
            assets = await call(s, 'photo_list_assets', {'task_id': t['task_id']})
            assert all(a['status'] == 'VERIFIED' and a['lr_status'] == 'EXPORTED' for a in assets['items'])
            assert (await call(s, 'photo_verify_preview', {'task_id': t['task_id']}))['status'] == 'OK'
            assert list(Path(w.config['preview_root']).rglob('*.jpg'))
            assert await call(s, 'photo_execute_import', {'task_id': t['task_id']}) == done
            with db.connect(w.home) as c:
                assert c.execute('SELECT count(*) FROM task_steps').fetchone()[0] == 5
                audit = list(c.execute('SELECT actor, action FROM audit_log'))
            assert any(a.startswith('ai:') and action == 'execute' for a, action in audit)
            assert any(a.startswith('human:') and action == 'approve' for a, action in audit)
            assert not any(a.startswith('ai:') and action == 'approve' for a, action in audit)
    run(scenario())


@pytest.mark.parametrize('change', ['preset', 'max_edge', 'quality', 'preview_root', 'library_root', 'plan_json', 'different_preset'])
def test_approved_changes_denied_without_work(env, change, tmp_path):
    w, t = prepare(env)
    w.add_preset('other')
    w.approve(t['task_id'], t['plan_digest'])
    if change == 'preset': w.config['presets']['preset']['label'] = 'changed'
    elif change in ('max_edge', 'quality'): w.config['preview'] = {change: 12}
    elif change in ('preview_root', 'library_root'): w.config[change] = str(tmp_path / 'changed')
    elif change == 'plan_json':
        plan = dict(t['plan']); plan['destination'] = 'changed'
        with db.connect(w.home) as c:
            c.execute('UPDATE tasks SET plan_json=? WHERE task_id=?', (json.dumps(plan), t['task_id']))
    with pytest.raises(PermissionDenied, match=('plan changed after approval' if change == 'plan_json' else 'preset differs' if change == 'different_preset' else 'preset/export settings changed after approval')):
        if change == 'different_preset': w.execute_lightroom(t['task_id'], ['lr_preset'], preset_id='other')
        else: w.execute(t['task_id'])
    with db.connect(w.home) as c:
        assert c.execute('SELECT state FROM tasks WHERE task_id=?', (t['task_id'],)).fetchone()[0] == 'WAITING_APPROVAL'
        assert c.execute('SELECT count(*) FROM task_steps').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM previews').fetchone()[0] == 0
    assert not list((tmp_path / 'preview').rglob('*'))


def test_single_stage_checks_snapshot_and_unapproved_order(env):
    w, t = prepare(env)
    w.config['preview'] = {'quality': 1}
    with pytest.raises(NotApproved): w.execute_lightroom(t['task_id'], ['lr_register'])
    with pytest.raises(NotApproved): w.execute(t['task_id'])
    w.approve(t['task_id'], t['plan_digest'])
    with pytest.raises(PermissionDenied, match='preset/export settings changed after approval'):
        w.execute_lightroom(t['task_id'], ['lr_register'])


def test_partial_export_retry_by_ai(env):
    w, t = prepare(env, 3)
    aid = t['plan']['files'][1]['asset_id']
    w.adapter.failures['export'] = {aid}
    w.approve(t['task_id'], t['plan_digest'])
    ai = Workbench(w.home, principal=ai_principal(), adapter=w.adapter)
    assert ai.execute(t['task_id'])['state'] == 'FAILED'
    before = list(w.adapter.calls)
    w.adapter.failures.clear()
    assert ai.retry(t['task_id'])['state'] == 'COMPLETED'
    assert approvals(w) == 1
    assert [call for call in w.adapter.calls[len(before):] if call[0] in ('register', 'preset')] == []
    assert ('export', aid) in w.adapter.calls[len(before):]
    with db.connect(w.home) as c:
        for stage in STAGES[:3]:
            assert c.execute('SELECT count(*) FROM task_steps WHERE stage=?', (stage,)).fetchone()[0] == 1
    assert w.verify_preview(t['task_id'])['status'] == 'OK'


def test_mcp_defaults_and_descriptions(env):
    w, card = env
    (card / 'one.RAF').write_bytes(b'raw')
    w.add_preset('preset')
    args = dict(order_id='order', photographer_id='p', source_id='card')
    async def scenario():
        async with client(w.home) as s:
            listing = await s.list_tools()
            assert len(listing.tools) == 14 and {tool.name for tool in listing.tools} == TOOLS
            assert all(tool.description for tool in listing.tools)
            assert not any(tool.name.startswith('approve') for tool in listing.tools)
            desc = next(tool.description for tool in listing.tools if tool.name == 'photo_plan_import')
            assert all(word in desc.lower() for word in ['approval', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify'])
            error = await call(s, 'photo_plan_import', args, 'INVALID_ARGUMENT')
            assert 'preset_id' in error['message'] and "stages=['ingest']" in error['message']
            full = await call(s, 'photo_plan_import', {**args, 'preset_id': 'preset'})
            assert full['plan']['stages'] == STAGES
            ingest = await call(s, 'photo_plan_import', {**args, 'stages': ['ingest']})
            assert ingest['plan']['stages'] == ['ingest'] and 'lightroom' not in ingest['plan']
    run(scenario())


def test_mcp_in_process_default_flow(env):
    from cetacea.mcp_server import create_server
    w, card = env
    (card / 'one.RAF').write_bytes(b'raw')
    w.add_preset('preset')
    args = dict(order_id='order', photographer_id='p', source_id='card')
    async def scenario():
        server = create_server(w.home)
        tools = await server.list_tools()
        assert len(tools) == 14 and all(t.description for t in tools)
        invoke = lambda name, args: server._tool_manager.get_tool(name).fn(**args)
        invalid = invoke('photo_plan_import', args)
        assert invalid.is_error and invalid.structured_content['code'] == 'INVALID_ARGUMENT'
        planned = invoke('photo_plan_import', {**args, 'preset_id': 'preset'}).structured_content
        assert planned['state'] == 'WAITING_APPROVAL' and planned['plan']['stages'] == STAGES
        tid = planned['task_id']
        denied = invoke('photo_execute_import', {'task_id': tid})
        assert denied.is_error and denied.structured_content['code'] == 'NOT_APPROVED'
        w.approve(tid, planned['plan_digest'])
        done = invoke('photo_execute_import', {'task_id': tid})
        assert done.structured_content['state'] == 'COMPLETED'
        assert w.verify_preview(tid)['status'] == 'OK' and approvals(w) == 1
    run(scenario())
