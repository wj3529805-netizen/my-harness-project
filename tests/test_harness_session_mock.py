"""MOCK Harness integration only; no model service is contacted."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from cetacea.harness_client import BudgetExceeded, HarnessError, HarnessSession

ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(os.environ.get('CETACEA_HARNESS_DIR', ROOT / 'third_party-review' / 'deepseek-harness'))
if not (HARNESS / 'node_modules').is_dir() or not shutil.which('bash'):
    pytest.skip(f'Harness deps not installed at {HARNESS} (see docs/THIRD_PARTY.md for the pnpm install --ignore-scripts recipe)', allow_module_level=True)

STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']


def cli(w, *args):
    r = subprocess.run([sys.executable, '-m', 'cetacea.cli', '--home', str(w.home), '--json', *args], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout)


def body(result, index=0):
    return json.loads(result.tool_results[index][1].removeprefix('Error: '))


@pytest.fixture
def session(tmp_path, env):
    w, card = env
    script = tmp_path / 'script.json'
    work = tmp_path / 'work'; work.mkdir()
    def make(turns, **kwargs):
        script.write_text(json.dumps({'turns': turns}))
        overrides = {'CETACEA_HARNESS_DIR': str(HARNESS), 'CETACEA_PYTHON': sys.executable}
        overrides.update(kwargs.pop('env', {}))
        return HarnessSession('mock', w.home, env=overrides, script_path=script, work_path=work, **kwargs)
    return w, card, script, make


def send(session, task='test'):
    try: return session.send(task)
    except HarnessError as e:
        if 'code 3' in str(e): pytest.skip('Node >= 24.9 not available')
        raise


def test_multiturn(session):
    w, card, script, make = session
    (card / 'one.RAF').write_bytes(b'raw one'); (card / 'one.JPG').write_bytes(b'jpg one')
    w.add_preset('preset', 'MOCK preset')
    args = dict(order_id='order', photographer_id='p', source_id='card', preset_id='preset', stages=STAGES)
    turns = [{'steps': [{'tool': 'mcp__cetacea__photo_plan_import', 'args': args}, {'tool': 'mcp__cetacea__photo_get_task', 'args': {'task_id': '$last.task_id'}}], 'final': 'MOCK awaiting approval'}]
    with make(turns) as s:
        first = send(s)
        planned = body(first)
        assert body(first, 1)['state'] == 'WAITING_APPROVAL' and first.requests == 3
        cli(w, 'approve', planned['task_id'], planned['plan_digest'])
        turns.append({'steps': [{'tool': 'mcp__cetacea__photo_execute_import', 'args': {'task_id': planned['task_id']}}], 'final': 'MOCK done'})
        script.write_text(json.dumps({'turns': turns}))
        second = send(s)
        assert second.success and second.requests == 2 and body(second)['state'] == 'COMPLETED' and body(second)['mock'] is True
    from cetacea import db
    with db.connect(w.home) as c: actors = list(c.execute('SELECT actor, action FROM audit_log'))
    assert any(a == 'human:cli' and 'approv' in action for a, action in actors)
    assert any(a.startswith('ai:') for a, _ in actors)
    assert not any(a.startswith('ai:') and 'approv' in action for a, action in actors)


def test_text_only(session, capsys):
    _, _, _, make = session
    with make([{'steps': [], 'final': 'MOCK answer'}]) as s: result = send(s)
    assert not result.success and any(w.code == 'NO_TOOL_CALLS' for w in result.warnings)
    assert 'WARNING [NO_TOOL_CALLS]' in capsys.readouterr().err
    assert result.requests == 1


def test_not_approved(session):
    w, card, _, make = session
    (card / 'one.RAF').write_bytes(b'raw')
    plan = w.plan_import('order', 'p', 'card', stages=STAGES)
    with make([{'steps': [{'tool': 'mcp__cetacea__photo_execute_import', 'args': {'task_id': plan['task_id']}}]}]) as s: result = send(s)
    assert result.tool_results[0][2] and body(result)['code'] == 'NOT_APPROVED'
    assert any(w.code == 'TOOL_CALL_FAILED' and 'NOT_APPROVED' in w.message for w in result.warnings)
    assert not list(Path(w.config['library_root']).rglob('*'))


def test_budget(session, tmp_path):
    _, _, _, make = session
    ledger = tmp_path / 'ledger.json'
    steps = [{'tool': 'mcp__cetacea__photo_list_orders', 'args': {}}] * 2
    with make([{'steps': steps}], ledger_path=ledger, max_requests=1) as s:
        with pytest.raises(BudgetExceeded): send(s)
    assert json.loads(ledger.read_text())['count'] >= 1


def test_missing_key(env, monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    with pytest.raises(HarnessError, match='code 5'):
        with HarnessSession('deepseek', env[0].home): pass


def test_override(session, capsys):
    _, _, _, make = session
    with make([{'steps': []}], env={'CETACEA_NO_TOOL_CALLING_MODELS': 'cetacea-mock/cetacea-mock'}) as s:
        assert any(w.code == 'MODEL_NO_TOOL_CALLING' for w in s.warnings)
    assert 'WARNING [MODEL_NO_TOOL_CALLING]' in capsys.readouterr().err


def test_tool_surface(session):
    _, _, _, make = session
    with make([{'steps': []}]) as s:
        result = s.send('inspect tools', require_tools=False)
    cetacea = {'photo_list_orders', 'photo_list_sources', 'photo_scan_source', 'photo_plan_import',
               'photo_execute_import', 'photo_get_task', 'photo_cancel_task', 'photo_retry_task',
               'photo_list_assets', 'photo_verify_preview', 'lightroom_get_status',
               'lightroom_import_verified', 'lightroom_apply_preset', 'lightroom_export_preview'}
    harmless = {'create_goal', 'get_goal', 'update_goal', 'todo_write', 'list_mcp_resources',
                'list_mcp_resource_templates', 'read_mcp_resource'}
    assert result.tool_surface == sorted({f'mcp__cetacea__{name}' for name in cetacea} | harmless)
    assert not any('bash' in name or name.startswith('fs') for name in result.tool_surface)


def test_default_full_pipeline_one_approval(session):
    from cetacea import db
    w, card, script, make = session
    (card / 'one.RAF').write_bytes(b'raw')
    w.add_preset('preset', 'MOCK preset')
    args = dict(order_id='order', photographer_id='p', source_id='card', preset_id='preset')
    turns = [{'steps': [{'tool': 'mcp__cetacea__photo_plan_import', 'args': args}], 'final': 'MOCK awaiting approval'}]
    with make(turns) as s:
        planned = body(send(s))
        assert planned['state'] == 'WAITING_APPROVAL' and planned['plan']['stages'] == STAGES
        cli(w, 'approve', planned['task_id'], planned['plan_digest'])
        turns.append({'steps': [{'tool': 'mcp__cetacea__photo_execute_import', 'args': {'task_id': planned['task_id']}}], 'final': 'MOCK done'})
        script.write_text(json.dumps({'turns': turns}))
        result = send(s)
        assert result.success and body(result)['state'] == 'COMPLETED' and body(result)['mock'] is True
    assert w.verify_preview(planned['task_id'])['status'] == 'OK'
    with db.connect(w.home) as c:
        assert c.execute('SELECT count(*) FROM approvals').fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM previews WHERE status="EXPORTED"').fetchone()[0] > 0
