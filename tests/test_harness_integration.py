"""Phase 2: deepseek-harness (pinned, experimental) as MCP client front-end for the CETACEA MCP server.

These tests boot the REAL Harness `headless` agent loop (Node >= 24.9, its own MCP client plugin
@deepseek-ai/dsh-mcp-client) via harness/run_headless.sh. The *model* is a scripted MOCK adapter
(harness/overlay/cetacea-mock-llm.ts): no API key, no network model call, no paid service.
They prove Harness <-> CETACEA stdio MCP wiring and shared state with the CLI; they do NOT prove
anything about a real LLM's tool-calling quality, macOS, or real Lightroom.
Skipped (with reason) when the Harness checkout/Node 24 is not available.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'harness' / 'run_headless.sh'
HARNESS = Path(os.environ.get('CETACEA_HARNESS_DIR', ROOT / 'third_party-review' / 'deepseek-harness'))
TOOLS = {'photo_list_orders', 'photo_list_sources', 'photo_scan_source', 'photo_plan_import', 'photo_execute_import', 'photo_get_task', 'photo_cancel_task', 'photo_retry_task', 'photo_list_assets', 'lightroom_get_status', 'lightroom_import_verified', 'lightroom_apply_preset', 'lightroom_export_preview', 'photo_verify_preview'}
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']
# Allowlist of the NON-cetacea tools the model may be offered: goal/todo bookkeeping and MCP-resource listing only (no shell, fs, web, subagent).
ALLOWED_HARNESS_TOOLS = {'create_goal', 'get_goal', 'update_goal', 'todo_write', 'list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource'}

if not (HARNESS / 'node_modules').is_dir() or not shutil.which('bash'):
    pytest.skip(f'Harness deps not installed at {HARNESS} (see docs/THIRD_PARTY.md for the pnpm install --ignore-scripts recipe)', allow_module_level=True)


class Turn:
    def __init__(self, stdout):
        self.events, self.result = [], None
        for line in stdout.splitlines():
            try: d = json.loads(line)
            except ValueError: continue
            if d.get('type') == 'session_event': self.events.append(d['event'])
            elif d.get('type') == 'result': self.result = d
    def of(self, kind): return [e['data'] for e in self.events if e['type'] == kind]
    @property
    def calls(self): return self.of('tool/call')
    @property
    def results(self):
        out = []
        for d in self.of('tool/result'):
            m = d['message']; text = ''.join(b.get('text', '') for b in m['content'])
            body = text[len('Error: '):] if text.startswith('Error: ') else text  # Harness prefixes failed MCP calls
            try: body = json.loads(body)
            except ValueError: body = {'raw': text}
            out.append((m['isError'], body))
        return out


@pytest.fixture
def harness(tmp_path, env):
    w, card = env
    log = tmp_path / 'mock-requests.jsonl'
    def go(steps, final='MOCK done', task='do the task'):
        script = tmp_path / 'script.json'
        script.write_text(json.dumps({'steps': steps, 'final': final}))
        environ = {**os.environ, 'CETACEA_HOME': str(w.home), 'CETACEA_PYTHON': sys.executable,
                   'CETACEA_HARNESS_DIR': str(HARNESS), 'CETACEA_MOCK_LOG': str(log), 'CETACEA_AGENT_CWD': str(tmp_path / 'agent-cwd')}
        (tmp_path / 'agent-cwd').mkdir(exist_ok=True)
        # the child must never see a model key from our environment
        for k in list(environ):
            if any(w_ in k.upper() for w_ in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')): del environ[k]
        p = subprocess.run(['bash', str(RUNNER), str(script), task], capture_output=True, text=True, timeout=180, env=environ)
        if p.returncode == 3: pytest.skip('Node >= 24.9 not available: ' + p.stderr.strip())
        assert p.returncode == 0, p.stderr[-2000:]
        t = Turn(p.stdout)
        assert t.result is not None, p.stdout[-2000:]
        return t
    go.log = log
    return w, card, go


def cli(w, *args):
    r = subprocess.run([sys.executable, '-m', 'cetacea.cli', '--home', str(w.home), '--json', *args], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout)


def actors(w):
    from cetacea import db
    with db.connect(w.home) as c:
        return {(a, act) for a, act in c.execute('SELECT actor, action FROM audit_log')}


def test_harness_lists_cetacea_tools_and_hides_shell_fs_tools(harness):
    w, card, go = harness
    t = go([{'tool': 'mcp__cetacea__photo_list_orders', 'args': {}}], final='listed')
    offered = json.loads(go.log.read_text().splitlines()[0])['tools']
    assert {n[len('mcp__cetacea__'):] for n in offered if n.startswith('mcp__cetacea__')} == TOOLS
    extra = {n for n in offered if not n.startswith('mcp__cetacea__')}
    assert extra <= ALLOWED_HARNESS_TOOLS, f'unexpected Harness tools exposed to the model: {extra - ALLOWED_HARNESS_TOOLS}'
    assert t.result['output'] == 'listed'
    (is_err, data), = t.results
    assert not is_err and data['items'] == [{'order_id': 'order', 'title': 'Order'}]
    ai_actions = {act for a, act in actors(w) if a.startswith('ai:')}
    assert ai_actions and not any(x in ai_actions for x in ('execute', 'approve', 'plan_import')), ai_actions  # the call is audited as AI, read-only


def test_ai_plans_via_harness_human_approves_via_cli_ai_executes_via_harness(harness):
    w, card, go = harness
    (card / 'one.RAF').write_bytes(b'raw one'); (card / 'one.JPG').write_bytes(b'jpg one')
    w.add_preset('preset', 'MOCK preset')
    plan_args = dict(order_id='order', photographer_id='p', source_id='card', preset_id='preset', stages=STAGES)
    # 1. AI (Harness -> MCP) plans; it can read the task back
    t1 = go([{'tool': 'mcp__cetacea__photo_plan_import', 'args': plan_args},
             {'tool': 'mcp__cetacea__photo_get_task', 'args': {'task_id': '$last.task_id'}}])
    (e1, planned), (e2, got) = t1.results
    assert not e1 and not e2 and got['state'] == 'WAITING_APPROVAL'
    tid = planned['task_id']
    # 2. the CLI sees the AI's task (shared sqlite state); AI may not execute before human approval
    assert cli(w, 'task', 'show', tid)['state'] == 'WAITING_APPROVAL'
    t2 = go([{'tool': 'mcp__cetacea__photo_execute_import', 'args': {'task_id': tid}}])
    (denied, body), = t2.results
    assert denied and body['code'] == 'NOT_APPROVED'
    assert not list(Path(w.config['library_root']).rglob('*')), 'nothing may be written before approval'
    # 3. human approves with the CLI, AI executes through Harness
    cli(w, 'approve', tid, planned['plan_digest'])
    t3 = go([{'tool': 'mcp__cetacea__photo_execute_import', 'args': {'task_id': tid}},
             {'tool': 'mcp__cetacea__photo_list_assets', 'args': {'task_id': tid}},
             {'tool': 'mcp__cetacea__photo_verify_preview', 'args': {'task_id': tid}}])
    (e, done), (e2, assets), (e3, verified) = t3.results
    assert not (e or e2 or e3) and done['state'] == 'COMPLETED' and done['mock'] is True
    assert verified['status'] == 'OK'
    # 4. CLI reads the results back; audit log attributes each side correctly
    assert cli(w, 'task', 'show', tid)['state'] == 'COMPLETED'
    assert len(cli(w, 'assets', '--task-id', tid)) == len(assets['items']) == 2
    # independent byte check (not trusting the server's own status): every input is copied under the library root with identical SHA-256
    import hashlib
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    copied = {sha(p) for p in Path(w.config['library_root']).rglob('*') if p.is_file() and p.suffix in ('.RAF', '.JPG')}
    assert copied >= {sha(card / 'one.RAF'), sha(card / 'one.JPG')}
    seen = actors(w)
    # NOTE: actor strings are 'human:cli' and 'ai:ai:mcp' (Phase-1 naming quirk: actor_id defaults to 'ai:mcp'); compare the type prefix.
    assert {a.split(':')[0] for a, _ in seen} == {'human', 'ai'}
    assert any(a == 'human:cli' and 'approv' in act for a, act in seen)
    assert not any(a.startswith('ai:') and 'approv' in act for a, act in seen)


def test_harness_cannot_reach_forbidden_tools_or_arguments(harness):
    w, card, go = harness
    (card / 'one.RAF').write_bytes(b'raw')
    t = w.plan_import('order', 'p', 'card', stages=STAGES)
    marker = w.home.parent / 'harness-should-not-exist'
    bad = [{'tool': 'bash', 'args': {'command': f'touch {marker}', 'description': 'attempt shell escape'}},
           {'tool': 'mcp__cetacea__approve', 'args': {'task_id': t['task_id']}},
           {'tool': 'mcp__cetacea__photo_get_task', 'args': {'task_id': '../../etc'}}]
    turn = go(bad)
    assert len(turn.results) == 3 and all(is_err for is_err, _ in turn.results), turn.results
    assert 'raw' in turn.results[0][1] and 'bash' in turn.results[0][1]['raw'], turn.results[0]  # Harness reports an unknown tool
    assert not marker.exists()
    assert cli(w, 'task', 'show', t['task_id'])['state'] == 'WAITING_APPROVAL'


def test_text_only_model_makes_no_tool_call_and_leaves_state_unchanged(harness):
    """Harness has no 'model without tool calling' warning (only `inputModalities`); this is the closest honest
    substitute: a text-only model never touches CETACEA."""
    w, card, go = harness
    (card / 'one.RAF').write_bytes(b'raw')
    t = w.plan_import('order', 'p', 'card', stages=STAGES)
    before = actors(w)
    turn = go([], final='MOCK text-only answer')
    assert turn.result['output'] == 'MOCK text-only answer' and turn.calls == []
    assert actors(w) == before and cli(w, 'task', 'show', t['task_id'])['state'] == 'WAITING_APPROVAL'
