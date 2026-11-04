"""Tests for the incomplete R6 preflight building blocks, not acceptance."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/mac/r6_lightroom.py'
spec = importlib.util.spec_from_file_location('r6_lightroom', SCRIPT)
r6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r6)


@pytest.mark.parametrize('value', ['DCIM/143NZ6_3', 'DCIM', '..', '/absolute'])
def test_scope_rejected_before_filesystem_access(monkeypatch, value):
    def forbidden(*args, **kwargs):
        raise AssertionError('filesystem access')
    monkeypatch.setattr(r6, 'scoped_source', forbidden)
    with pytest.raises(r6.argparse.ArgumentTypeError, match='hard locked'):
        r6.scope_listing('/unused', value)


def test_source_uuid_precedence():
    args = r6.parser().parse_args(['--mode', 'r3', '--confirm-card-readonly'])
    with pytest.raises(ValueError):
        r6.source_uuid(args, {})
    assert r6.source_uuid(args, {'CETACEA_SOURCE_UUID': 'environment'}) == 'environment'
    args.source_uuid = 'argument'
    assert r6.source_uuid(args, {'CETACEA_SOURCE_UUID': 'environment'}) == 'argument'


def test_readonly_confirmation_required():
    with pytest.raises(SystemExit):
        r6.parser().parse_args(['--mode', 'r3'])


def test_scope_listing_and_extra_file(tmp_path, monkeypatch):
    source = tmp_path / r6.SCOPE
    source.mkdir(parents=True)
    sibling = source.parent / '143NZ6_3'
    sibling.mkdir()
    (sibling / 'decoy').write_bytes(b'decoy')
    for i in range(9):
        (source / f'{i}.NEF').write_bytes(b'raw')
        (source / f'{i}.JPG').write_bytes(b'jpg')
    original = r6.os.scandir
    def checked(path):
        assert not Path(path).is_relative_to(sibling)
        return original(path)
    monkeypatch.setattr(r6.os, 'scandir', checked)
    assert len(r6.scope_listing(tmp_path)) == 18
    (source / 'extra.TXT').write_bytes(b'extra')
    with pytest.raises(ValueError, match='Scope mismatch'):
        r6.scope_listing(tmp_path)
    (source / 'extra.TXT').unlink()
    (source / '0.NEF').unlink()
    with pytest.raises(ValueError, match='Scope mismatch'):
        r6.scope_listing(tmp_path)


@pytest.mark.parametrize('pids,catalogs,expected', [
    ('', [], False), ('1\n2\n', [], False),
    ('1', ['/test.lrcat', '/other.lrcat'], False),
    ('1', ['/other.lrcat'], False), ('1', ['/test.lrcat'], True),
])
def test_catalog_guard_does_not_open_catalog(monkeypatch, pids, catalogs, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError('catalog content must not be opened')
    monkeypatch.setattr(Path, 'open', forbidden)
    def runner(args):
        if args[0] == 'pgrep':
            if not pids:
                raise subprocess.CalledProcessError(1, args)
            return pids
        return '\n'.join('n' + c for c in catalogs)
    result = r6.catalog_guard('/test.lrcat', runner=runner)
    assert result['matches_expected'] is expected


def test_preset_probe_filters_private_names():
    class Adapter:
        def call_tool(self, name, arguments):
            return {'count': 2, 'presets': [{'name': 'private preset'}, {'name': 'wanted'}]}
    assert r6.preset_probe(Adapter(), 'wanted') == {'preset_found': True, 'matching_count': 1}
    assert r6.preset_probe(Adapter(), 'absent') == {'preset_found': False, 'matching_count': 0}


def make_run(tmp_path):
    mount = tmp_path / 'card'
    source = mount / r6.SCOPE
    source.mkdir(parents=True)
    sibling = source.parent / '143NZ6_3'
    sibling.mkdir()
    (sibling / 'decoy').write_bytes(b'decoy')
    for i in range(9):
        (source / f'{i}.NEF').write_bytes(b'fake nef')
        (source / f'{i}.JPG').write_bytes(b'fake jpg')
    target = tmp_path / 'target'
    target.mkdir()
    args = r6.parser().parse_args(['--mode', 'r3', '--confirm-card-readonly', '--source-uuid', 'fake-private-uuid', '--lightroom', 'mock', '--target-base', str(target), '--out', str(tmp_path / 'evidence')])
    return args, mount, sibling


def approve(w, task, timeout, interval):
    w.approve(task['task_id'], task['plan_digest'])


def test_complete_mock_run(tmp_path, monkeypatch):
    args, mount, sibling = make_run(tmp_path)
    original = r6.os.scandir
    def checked(path):
        assert not Path(path).is_relative_to(sibling)
        return original(path)
    monkeypatch.setattr(r6.os, 'scandir', checked)
    original_open = r6.os.open
    def checked_open(path, *args, **kwargs):
        if isinstance(path, (str, bytes, Path)):
            assert not Path(path).is_relative_to(sibling)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(r6.os, 'open', checked_open)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    expected = {'preflight.json', 'catalog-guard.json', 'reader.json', 'inventory-before.json', 'inventory-after.json', 'plan.json', 'approval.json', 'database.json', 'stage-timing.json', 'previews.json', 'verify-preview.json', 'lightroom-readback.json', 'nef-subtype-report.json', 'library-readback.json', 'result.json', 'README.md', 'console.txt'}
    assert {p.name for p in Path(args.out).iterdir()} == expected
    approval = r6.json.loads((Path(args.out) / 'approval.json').read_text())
    plan = r6.json.loads((Path(args.out) / 'plan.json').read_text())
    assert approval['count'] == 1 and approval['before'] == approval['after']
    assert approval['after'][0]['plan_digest'] == plan['plan_digest']
    assert plan['plan']['stages'] == r6.STAGES
    for path in Path(args.out).iterdir():
        r6.assert_clean(path)
        assert 'fake-private-uuid' not in path.read_text()


@pytest.mark.parametrize('mutation', ['missing', 'extra'])
def test_scope_mismatch_stops_before_task(tmp_path, mutation):
    args, mount, _ = make_run(tmp_path)
    source = mount / r6.SCOPE
    if mutation == 'missing':
        (source / '0.NEF').unlink()
    else:
        (source / 'extra.TXT').write_bytes(b'x')
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL_STOPPED'
    assert not list(Path(args.target_base).iterdir())
    assert not (Path(args.out) / 'plan.json').exists()
    assert (Path(args.out) / 'result.json').exists()


def test_preset_missing_stops(tmp_path):
    args, mount, _ = make_run(tmp_path)
    args.lightroom = 'real'
    args.lightroom_test_catalog_path = '/test.lrcat'
    class Adapter:
        def status(self): return 'Lightroom MCP connected'
        def call_tool(self, *_): return {'count': 1, 'presets': [{'name': 'private preset'}]}
    def runner(cmd): return '1' if cmd[0] == 'pgrep' else 'n/test.lrcat'
    result = r6.run(args, mount_resolver=lambda _: mount, command_runner=runner, adapter=Adapter())
    assert result['status'] == 'FAIL_STOPPED'
    assert 'private preset' not in (Path(args.out) / 'preflight.json').read_text()
    assert not list(Path(args.target_base).iterdir())


def test_ingest_failure_blocks_lightroom(tmp_path, monkeypatch):
    from cetacea.ingest.copier import CopyEngine
    args, mount, _ = make_run(tmp_path)
    original = CopyEngine.copy
    def fail(self, source, library, task_id, n, item):
        if n == 0: return {'status': 'FAILED', 'error': 'injected failure'}
        return original(self, source, library, task_id, n, item)
    monkeypatch.setattr(CopyEngine, 'copy', fail)
    lr = r6.MockLightroomAdapter(size=(1600, 1067))
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve, adapter=lr)
    assert result['status'] == 'FAIL', result
    data = r6.json.loads((Path(args.out) / 'database.json').read_text())
    assert [s['stage'] for s in data['task_steps']] == ['ingest']
    assert not lr.calls and not lr.ids


def test_lightroom_failure_no_retry(tmp_path):
    args, mount, _ = make_run(tmp_path)
    lr = r6.MockLightroomAdapter(failures={'register': {'0.NEF'}}, size=(1600, 1067))
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve, adapter=lr)
    assert result['status'] == 'FAIL', result
    data = r6.json.loads((Path(args.out) / 'database.json').read_text())
    assert data['task']['run_count'] == 1
    assert [s['stage'] for s in data['task_steps']] == ['ingest', 'lr_register']


def test_r4_rejected(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(r6.sys, 'argv', ['r6', '--mode', 'r4', '--confirm-card-readonly'])
    assert r6.main() == 1
    assert '已推迟' in capsys.readouterr().err


def test_preflight_does_not_read_source_contents(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    args.preflight_only = True
    original_open = r6.os.open
    def checked(path, *a, **kw):
        if isinstance(path, (str, Path)) and Path(path).is_relative_to(mount):
            raise AssertionError('preflight read source')
        return original_open(path, *a, **kw)
    monkeypatch.setattr(r6.os, 'open', checked)
    result = r6.run(args, mount_resolver=lambda _: mount)
    assert result['status'] == 'PREFLIGHT_OK_MOCK'
    assert not list(Path(args.target_base).iterdir())
    assert not (Path(args.out) / 'plan.json').exists()


@pytest.mark.parametrize('function', ['readback', 'subtype_report'])
def test_evidence_exception_after_execute_is_fail(tmp_path, monkeypatch, function):
    args, mount, _ = make_run(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('injected evidence failure')
    monkeypatch.setattr(r6.r3, function, fail)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL'
    assert any('injected evidence failure' in failure for failure in result['failures'])
    assert r6.json.loads((Path(args.out) / 'result.json').read_text())['status'] == 'FAIL'


def test_execute_exception_is_fail(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('injected execute failure')
    monkeypatch.setattr(r6.Workbench, 'execute', fail)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL'
    assert any('injected execute failure' in failure for failure in result['failures'])


@pytest.mark.parametrize('failed_guard', ['preflight', 'before_execute', 'after_execute'])
def test_catalog_guard_failure_at_each_stage(tmp_path, monkeypatch, failed_guard):
    args, mount, _ = make_run(tmp_path)
    args.lightroom = 'real'
    args.lightroom_test_catalog_path = '/test.lrcat'
    class Adapter(r6.MockLightroomAdapter):
        def status(self): return 'Lightroom MCP connected'
        def call_tool(self, name, arguments):
            return {'count': 1, 'presets': [{'name': args.preset_name}]}
    class Readback:
        def __init__(self, **kwargs): pass
        def call_tool(self, name, arguments):
            return {'photos': [{'developSettings': {'exposure': 0.5}}], 'missing': []}
    monkeypatch.setattr(r6, 'RealLightroomMcpAdapter', Readback)
    monkeypatch.setattr(r6, 'reader_info', lambda *a: {})
    monkeypatch.setattr(r6, 'catalog_guard', lambda expected, process, runner, label: {
        'label': label, 'matches_expected': label != failed_guard})
    execute_calls = []
    execute = r6.Workbench.execute
    def track_execute(w, *a, **kw):
        execute_calls.append(True)
        return execute(w, *a, **kw)
    monkeypatch.setattr(r6.Workbench, 'execute', track_execute)
    adapter = Adapter(size=(1600, 1067))
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve, adapter=adapter)
    guards = r6.json.loads((Path(args.out) / 'catalog-guard.json').read_text())
    assert guards[-1]['label'] == failed_guard and not guards[-1]['matches_expected']
    if failed_guard == 'after_execute':
        assert result['status'] == 'FAIL'
        assert execute_calls == [True]
        assert not result['checks']['catalog_guard']['passed']
        assert result['failures']
        for name in ('database.json', 'stage-timing.json', 'library-readback.json',
                     'lightroom-readback.json', 'previews.json', 'verify-preview.json'):
            assert (Path(args.out) / name).exists(), name
    else:
        assert result['status'] == 'FAIL_STOPPED'
        assert not execute_calls
        assert not adapter.calls
        assert not (Path(args.out) / 'database.json').exists()


def test_real_adapter_pipeline_under_write_guard(tmp_path):
    card = tmp_path / 'card'
    card.mkdir()
    (card / 'photo.NEF').write_bytes(b'fake raw')
    target = tmp_path / 'target'
    target.mkdir()
    home = tmp_path / 'home'
    w = r6.Workbench.init(home, target / 'library', target / 'preview')
    w.add_source('card', card)
    w.create_order('order', 'Order')
    w.add_photographer('tester', 'Test')
    w.add_preset('preset', lightroom_name='Test preset')
    w.adapter = r6.RealLightroomMcpAdapter(test_command=[sys.executable, str(Path(__file__).with_name('fake_lightroom_mcp.py'))])
    original_call = w.adapter.call_tool
    calls = []
    def call(name, arguments):
        response = original_call(name, arguments)
        calls.append(name)
        # The stateless fixture reports every photo present. Simulate a missing
        # first readback so registration also exercises its real import call.
        if name == 'get_photo_metadata' and calls.count(name) == 1:
            return {'photos': [], 'missing': arguments['photo_ids']}
        return response
    w.adapter.call_tool = call
    task = w.plan_import('order', 'tester', 'card', preset_id='preset', stages=r6.STAGES)
    w.approve(task['task_id'], task['plan_digest'])
    with r6.guard_writes([target, home, tempfile.gettempdir()], [card]):
        finished = w.execute(task['task_id'])
    assert finished['state'] == 'COMPLETED', finished
    with r6.db.connect(home) as conn:
        steps = [dict(row) for row in conn.execute('SELECT stage, state FROM task_steps WHERE task_id=? ORDER BY started_at', (task['task_id'],))]
    assert [row['stage'] for row in steps] == r6.STAGES
    assert all(row['state'] == 'COMPLETED' for row in steps)
    assert 'import_photos' in calls and 'export_photos' in calls
    assert w.verify_preview(task['task_id'])['status'] == 'OK'
