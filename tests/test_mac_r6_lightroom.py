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


def test_scope_listing_skips_apple_metadata(tmp_path):
    source = tmp_path / r6.SCOPE
    source.mkdir(parents=True)
    for i in range(9):
        (source / f'{i}.NEF').write_bytes(b'raw')
        (source / f'{i}.JPG').write_bytes(b'jpg')
    for name in ('NC_FLLST.DAT', '.DS_Store', '._0.NEF'):
        (source / name).write_bytes(b'metadata')

    names = {item['rel_path'] for item in r6.scope_listing(tmp_path)}
    assert len(names) == 19
    assert 'NC_FLLST.DAT' in names
    assert '.DS_Store' not in names and '._0.NEF' not in names

    (source / 'extra.TXT').write_bytes(b'extra')
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


def configure_runtime(args, tmp_path, monkeypatch):
    args.lightroom_node = str(tmp_path / 'node')
    args.lightroom_mcp_index = str(tmp_path / 'index.js')
    Path(args.lightroom_node).touch()
    Path(args.lightroom_mcp_index).touch()
    home = tmp_path / 'fake-home'
    token = home / '.config/lightroom-mcp/token'
    token.parent.mkdir(parents=True)
    token.touch()
    monkeypatch.setattr(Path, 'home', lambda: home)


def assert_evidence_clean(out):
    for path in Path(out).iterdir():
        r6.assert_clean(path)


def checks(out):
    return {item['name']: item for item in r6.json.loads((Path(out) / 'preflight.json').read_text())['checks']}


def test_missing_target_reports_safe_failure(tmp_path):
    args, mount, _ = make_run(tmp_path)
    args.preflight_only = True
    args.target_base = str(tmp_path / 'missing-target')
    result = r6.run(args, mount_resolver=lambda _: mount)
    assert result['status'] == 'FAIL_STOPPED'
    assert result['failed_step'] == 'target_volume_present'
    assert not checks(args.out)['target_volume_present']['passed']
    assert any('target_volume_present: FileNotFoundError' in x for x in result['failures'])
    assert str(tmp_path) not in str(result['failures'])
    assert not Path(args.target_base).exists()
    assert r6.json.loads((Path(args.out) / 'catalog-guard.json').read_text())
    assert_evidence_clean(args.out)


def test_multiple_runtime_failures_and_missing_card(tmp_path, monkeypatch):
    args, _, _ = make_run(tmp_path)
    args.lightroom = 'real'
    args.lightroom_test_catalog_path = '/test.lrcat'
    args.lightroom_node = str(tmp_path / 'missing-node')
    args.lightroom_mcp_index = str(tmp_path / 'missing-index')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'empty-home')
    def missing(_):
        raise FileNotFoundError('private path ' + str(tmp_path))
    def runner(cmd):
        return '1' if cmd[0] == 'pgrep' else 'n/test.lrcat'
    result = r6.run(args, mount_resolver=missing, command_runner=runner)
    items = checks(args.out)
    assert result['status'] == 'FAIL_STOPPED'
    for name in ('card_mounted', 'node_binary_exists', 'mcp_index_exists', 'bridge_token_exists'):
        assert not items[name]['passed'] and any(x.startswith(name + ':') for x in result['failures'])
    for name in ('scope_listing_9nef_9jpg', 'target_on_different_device', 'evidence_outside_card', 'mcp_connected', 'preset_found'):
        assert items[name]['skipped']
    assert str(tmp_path) not in str(result['failures'])
    assert r6.json.loads((Path(args.out) / 'catalog-guard.json').read_text())
    assert_evidence_clean(args.out)


def test_default_index_candidates(tmp_path):
    repo = tmp_path / 'my-harness-project'
    sibling = tmp_path / 'cetacea-workbench'
    suffix = '.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js'
    first, second = repo / suffix, sibling / suffix
    assert r6.default_mcp_index(repo) == str(first)
    second.parent.mkdir(parents=True)
    second.touch()
    assert r6.default_mcp_index(repo) == str(second)
    first.parent.mkdir(parents=True)
    first.touch()
    assert r6.default_mcp_index(repo) == str(first)


def approve(w, task, timeout, interval):
    w.approve(task['task_id'], task['plan_digest'])


def separate_card_device(monkeypatch, mount):
    original = Path.stat
    def stat(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == mount:
            fields = list(value)
            fields[2] += 1000000
            return r6.os.stat_result(fields)
        return value
    monkeypatch.setattr(Path, 'stat', stat)


def test_persistent_custom_home(tmp_path, monkeypatch, capsys):
    args, mount, _ = make_run(tmp_path)
    separate_card_device(monkeypatch, mount)
    home = tmp_path / 'persistent-home'
    home.mkdir()
    args.home_dir = str(home)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    assert (home / 'state.sqlite3').is_file()
    assert result['home_persistent'] and result['home_location'] == 'custom'
    assert str(home) in capsys.readouterr().out
    assert checks(args.out)['home_dir_safe']['passed']
    assert_evidence_clean(args.out)
    for path in Path(args.out).iterdir():
        assert str(home) not in path.read_text()


@pytest.mark.parametrize('case', ['nonempty', 'symlink', 'card', 'same_device', 'library', 'preview', 'evidence', 'relative', 'missing_parent'])
def test_unsafe_custom_home_stops_before_task(tmp_path, monkeypatch, case):
    args, mount, _ = make_run(tmp_path)
    if case != 'same_device':
        separate_card_device(monkeypatch, mount)
    home = tmp_path / 'home'
    if case == 'nonempty':
        home.mkdir()
        (home / 'keep').touch()
    elif case == 'symlink':
        home.symlink_to(tmp_path, target_is_directory=True)
    elif case == 'card':
        home = mount / 'home'
    elif case in ('library', 'preview'):
        home = Path(args.target_base) / 'Cetacea-R6-Test-old' / case
    elif case == 'evidence':
        home = Path(args.out)
    elif case == 'relative':
        home = Path('relative-home')
    elif case == 'missing_parent':
        home = tmp_path / 'missing' / 'home'
    args.home_dir = str(home)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL_STOPPED'
    assert result['failed_step'] == 'home_dir_safe'
    assert not checks(args.out)['home_dir_safe']['passed']
    assert not list(Path(args.target_base).iterdir())
    assert not (Path(args.out) / 'plan.json').exists()


def test_preflight_does_not_create_custom_home(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    separate_card_device(monkeypatch, mount)
    home = tmp_path / 'new-home'
    args.home_dir = str(home)
    args.preflight_only = True
    result = r6.run(args, mount_resolver=lambda _: mount)
    assert result['status'] == 'PREFLIGHT_OK_MOCK'
    assert checks(args.out)['home_dir_safe']['passed']
    assert not home.exists()


def test_home_on_target(tmp_path):
    args, mount, _ = make_run(tmp_path)
    args.home_on_target = True
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    target = next(Path(args.target_base).iterdir())
    assert (target / 'home' / 'state.sqlite3').is_file()
    assert result['home_persistent'] and result['home_location'] == 'target'
    assert_evidence_clean(args.out)
    for path in Path(args.out).iterdir():
        assert str(target / 'home') not in path.read_text()


def test_home_options_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        r6.parser().parse_args(['--mode', 'r3', '--confirm-card-readonly', '--home-dir', '/tmp/home', '--home-on-target'])


def test_complete_mock_run(tmp_path, monkeypatch):
    args, mount, sibling = make_run(tmp_path)
    (mount / r6.SCOPE / 'NC_FLLST.DAT').write_bytes(b'camera list')
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
    lr = r6.MockLightroomAdapter(size=(1600, 1067))
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve, adapter=lr)
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    assert result['home_location'] == 'tmp' and not result['home_persistent']
    assert result['home'] == '<RUN_HOME>' and 'purged on reboot' in result['notes'][0]
    assert 'purged on reboot' in (Path(args.out) / 'README.md').read_text()
    assert checks(args.out)['home_dir_safe']['skipped']
    assert result['counts'] == {'nef': 9, 'jpg': 9, 'other': 1}
    assert all(result['checks'][name]['passed'] for name in ('verified_library', 'ingest', 'other_never_in_lightroom'))
    assert '19' in result['checks']['verified_library']['reason'] and '19' in result['checks']['ingest']['reason']
    assert {s['stage']: s['succeeded'] for s in result['lightroom_stage_summary']} == dict(ingest=19, lr_register=9, lr_preset=9, lr_export=9, preview_verify=9)
    expected = {'preflight.json', 'catalog-guard.json', 'reader.json', 'inventory-before.json', 'inventory-after.json', 'plan.json', 'approval.json', 'database.json', 'stage-timing.json', 'previews.json', 'verify-preview.json', 'lightroom-readback.json', 'nef-subtype-report.json', 'library-readback.json', 'result.json', 'README.md', 'console.txt'}
    assert {p.name for p in Path(args.out).iterdir()} == expected
    approval = r6.json.loads((Path(args.out) / 'approval.json').read_text())
    plan = r6.json.loads((Path(args.out) / 'plan.json').read_text())
    assert approval['count'] == 1 and approval['before'] == approval['after']
    assert approval['after'][0]['plan_digest'] == plan['plan_digest']
    assert plan['plan']['stages'] == r6.STAGES
    dat = next(f for f in plan['plan']['files'] if f['rel_path'] == 'NC_FLLST.DAT')
    assert dat['kind'] == 'other' and all(dat['asset_id'] not in call for call in lr.calls)
    for name in ('inventory-before.json', 'inventory-after.json', 'library-readback.json'):
        assert 'NC_FLLST.DAT' in (Path(args.out) / name).read_text()
    for path in Path(args.out).iterdir():
        r6.assert_clean(path)
        assert 'fake-private-uuid' not in path.read_text()


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'other_dat', 'lowercase', 'two_dat', 'duplicate_case', 'directory', 'symlink'])
def test_scope_mismatch_stops_before_task(tmp_path, mutation):
    args, mount, _ = make_run(tmp_path)
    source = mount / r6.SCOPE
    if mutation == 'missing':
        (source / '0.NEF').unlink()
    elif mutation == 'extra':
        (source / 'extra.TXT').write_bytes(b'x')
    elif mutation == 'other_dat':
        (source / 'other.DAT').write_bytes(b'x')
    elif mutation == 'lowercase':
        (source / 'nc_fllst.dat').write_bytes(b'x')
    elif mutation == 'two_dat':
        (source / 'NC_FLLST.DAT').write_bytes(b'x')
        (source / 'other.DAT').write_bytes(b'x')
    elif mutation == 'duplicate_case':
        (source / 'NC_FLLST.DAT').write_bytes(b'x')
        (source / 'nc_fllst.dat').write_bytes(b'x')
    elif mutation == 'directory':
        (source / 'NC_FLLST.DAT').mkdir()
    else:
        (source / 'NC_FLLST.DAT').symlink_to(source / '0.NEF')
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL_STOPPED'
    assert not checks(args.out)['scope_listing_9nef_9jpg']['passed']
    assert not list(Path(args.target_base).iterdir())
    assert not (Path(args.out) / 'plan.json').exists()
    assert (Path(args.out) / 'result.json').exists()


def test_preset_missing_stops(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    args.lightroom = 'real'
    args.lightroom_test_catalog_path = '/test.lrcat'
    configure_runtime(args, tmp_path, monkeypatch)
    class Adapter:
        def status(self): return 'Lightroom MCP connected'
        def call_tool(self, *_): return {'count': 1, 'presets': [{'name': 'private preset'}]}
    def runner(cmd): return '1' if cmd[0] == 'pgrep' else 'n/test.lrcat'
    result = r6.run(args, mount_resolver=lambda _: mount, command_runner=runner, adapter=Adapter())
    assert result['status'] == 'FAIL_STOPPED'
    assert not checks(args.out)['preset_found']['passed']
    assert any(x.startswith('preset_found:') for x in result['failures'])
    assert_evidence_clean(args.out)
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


@pytest.mark.parametrize('with_dat', [False, True])
def test_preflight_does_not_read_source_contents(tmp_path, monkeypatch, with_dat):
    args, mount, _ = make_run(tmp_path)
    if with_dat:
        (mount / r6.SCOPE / 'NC_FLLST.DAT').write_bytes(b'camera list')
    args.preflight_only = True
    original_open = r6.os.open
    def checked(path, *a, **kw):
        if isinstance(path, (str, Path)) and Path(path).is_relative_to(mount):
            raise AssertionError('preflight read source')
        return original_open(path, *a, **kw)
    monkeypatch.setattr(r6.os, 'open', checked)
    result = r6.run(args, mount_resolver=lambda _: mount)
    assert result['status'] == 'PREFLIGHT_OK_MOCK'
    assert result['counts'] == {'nef': 9, 'jpg': 9, 'other': int(with_dat)}
    assert r6.json.loads((Path(args.out) / 'preflight.json').read_text())['counts'] == result['counts']
    assert not list(Path(args.target_base).iterdir())
    assert not (Path(args.out) / 'plan.json').exists()


def test_other_registered_fails_acceptance(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    (mount / r6.SCOPE / 'NC_FLLST.DAT').write_bytes(b'camera list')
    original = r6.Workbench.list_assets
    def tampered(w, *a, **kw):
        assets = original(w, *a, **kw)
        # Affect only the evidence read after the pipeline has completed.
        if any(asset['lr_status'] == 'EXPORTED' for asset in assets):
            for asset in assets:
                if asset['kind'] == 'other':
                    asset['lr_photo_id'] = 'fake-registered'
                    asset['lr_status'] = 'REGISTERED'
        return assets
    monkeypatch.setattr(r6.Workbench, 'list_assets', tampered)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL', result
    assert not result['checks']['other_never_in_lightroom']['passed']


@pytest.mark.parametrize('function', ['readback', 'subtype_report'])
def test_evidence_exception_after_execute_is_fail(tmp_path, monkeypatch, function):
    args, mount, _ = make_run(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('injected evidence failure')
    monkeypatch.setattr(r6.r3, function, fail)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL'
    assert any('execution_evidence: RuntimeError' in failure for failure in result['failures'])
    assert r6.json.loads((Path(args.out) / 'result.json').read_text())['status'] == 'FAIL'


def test_execute_exception_is_fail(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('injected execute failure')
    monkeypatch.setattr(r6.Workbench, 'execute', fail)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL'
    assert any('execute: RuntimeError' in failure for failure in result['failures'])


@pytest.mark.parametrize('failed_guard', ['preflight', 'before_execute', 'after_execute'])
def test_catalog_guard_failure_at_each_stage(tmp_path, monkeypatch, failed_guard):
    args, mount, _ = make_run(tmp_path)
    args.lightroom = 'real'
    args.lightroom_test_catalog_path = '/test.lrcat'
    configure_runtime(args, tmp_path, monkeypatch)
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
        'label': label, 'process_count': 1, 'matches_expected': label != failed_guard})
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

class NestedMock(r6.MockLightroomAdapter):
    def export_jpeg(self, photo_refs, dest_dir, max_edge=1600, quality=85):
        results = []
        for ref in photo_refs:
            directory = Path(dest_dir) / ref.asset_id
            directory.mkdir()
            results.extend(super().export_jpeg([ref], directory, max_edge, quality))
        return results


@pytest.fixture
def completed_nested(tmp_path, monkeypatch):
    args, mount, _ = make_run(tmp_path)
    (mount / r6.SCOPE / 'NC_FLLST.DAT').write_bytes(b'camera list')
    homes = []
    original = r6.tempfile.mkdtemp
    def capture(*a, **kw):
        path = original(*a, **kw); homes.append(path); return path
    monkeypatch.setattr(r6.tempfile, 'mkdtemp', capture)
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve, adapter=NestedMock(size=(1600, 1067)))
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    assert all(item['passed'] for item in result['checks'].values())
    task = r6.json.loads((Path(args.out) / 'plan.json').read_text())['task_id']
    args.rejudge = True
    args.rejudge_home = homes[0]
    args.rejudge_task = task
    args.rejudge_from = args.out
    args.out = str(tmp_path / 'rejudge')
    return args, mount


def test_nested_rejudge_readonly(completed_nested, monkeypatch):
    args, mount = completed_nested
    class Spy(NestedMock):
        def register(self, *a, **k): raise AssertionError('register called')
        def apply_preset(self, *a, **k): raise AssertionError('preset called')
        def export_jpeg(self, *a, **k): raise AssertionError('export called')
    import sqlite3
    with sqlite3.connect(Path(args.rejudge_home) / 'state.sqlite3') as c:
        count = c.execute('SELECT count(*) FROM tasks').fetchone()[0]
    result = r6.run(args, mount_resolver=lambda _: mount, adapter=Spy())
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    assert result['rejudge'] and not result['adapter_calls_observed']
    assert all(item['passed'] for item in result['checks'].values())
    with sqlite3.connect(Path(args.rejudge_home) / 'state.sqlite3') as c:
        assert c.execute('SELECT count(*) FROM tasks').fetchone()[0] == count
    assert_evidence_clean(args.out)


@pytest.mark.parametrize('mutation,check', [('library', 'verified_library'), ('source', 'source_unchanged'), ('approval', 'approval')])
def test_rejudge_detects_changes(completed_nested, mutation, check):
    args, mount = completed_nested
    if mutation == 'library':
        cfg = r6.config.load(Path(args.rejudge_home))
        file = next(p for p in Path(cfg['library_root']).rglob('*') if p.is_file())
        file.write_bytes(b'changed')
    elif mutation == 'source':
        (mount / r6.SCOPE / '0.NEF').write_bytes(b'changed')
    else:
        import sqlite3
        with sqlite3.connect(Path(args.rejudge_home) / 'state.sqlite3') as c:
            c.execute('DELETE FROM approvals')
        c.close()
    result = r6.run(args, mount_resolver=lambda _: mount)
    assert result['status'] == 'FAIL', result
    assert not result['checks'][check]['passed']


@pytest.mark.parametrize('same', [True, False])
def test_rejudge_rejects_existing_output(completed_nested, same):
    args, mount = completed_nested
    if same: args.out = args.rejudge_from
    else: Path(args.out).mkdir()
    with pytest.raises(ValueError, match='output'):
        r6.run(args, mount_resolver=lambda _: mount)


def test_preview_outside_run_is_check_failure(tmp_path):
    task = {'order_id': 'r3', 'photographer_id': 'tester', 'batch_id': 'batch', 'task_id': 'task'}
    previews = [{'run': 1, 'path': str(tmp_path / 'outside.jpg'), 'asset_id': 'asset'}]
    rows, pairs, valid, manifests = r6.preview_evidence(previews, [], task, tmp_path)
    assert not valid and not rows and not pairs and not manifests


def make_large_run(tmp_path):
    args, mount, sibling = make_run(tmp_path)
    (sibling / 'decoy').unlink()
    for i in range(12):
        (sibling / f'DSC_{i:04}.NEF').write_bytes(b'fake nef')
        (sibling / f'DSC_{i:04}.JPG').write_bytes(b'fake jpg')
    (sibling / 'DSC_0558.JPG').write_bytes(b'unpaired')
    (sibling / 'NC_FLLST.DAT').write_bytes(b'dat')
    args.mode = 'large'
    args.source_subdir = r6.LARGE_SCOPE
    args.expect_nef, args.expect_jpg = 12, 13
    return args, mount


def test_large_mock_all_and_throughput(tmp_path):
    args, mount = make_large_run(tmp_path)
    lr = r6.MockLightroomAdapter(size=(1600, 1067))
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve, adapter=lr)
    assert result['status'] == 'PASS_MOCK_NOT_REAL_LIGHTROOM', result
    assert result['lr_scope'] == {'mode': 'all', 'count': 12, 'total_raw': 12}
    assert result['counts'] == {'nef': 12, 'jpg': 13, 'other': 1}
    assert all(c['passed'] for c in result['checks'].values())
    assert {s['stage']: s['succeeded'] for s in result['lightroom_stage_summary']} == dict(ingest=26, lr_register=12, lr_preset=12, lr_export=12, preview_verify=12)
    assert 'DSC_0558.JPG' not in str(lr.calls)
    stats = r6.json.loads((Path(args.out) / 'throughput.json').read_text())
    assert stats == result['throughput'] and stats['total_wall_s'] > 0
    assert stats['peak_rss'] > 0 and stats['peak_rss_unit'] in ('bytes', 'KiB')
    assert stats['stages']['ingest']['items'] == 26 and stats['stages']['ingest']['bytes'] > 0
    assert_evidence_clean(args.out)


def test_large_count_mismatch_stops(tmp_path):
    args, mount = make_large_run(tmp_path)
    args.expect_jpg = 12
    result = r6.run(args, mount_resolver=lambda _: mount, approval_waiter=approve)
    assert result['status'] == 'FAIL_STOPPED'
    assert not (Path(args.out) / 'plan.json').exists()


@pytest.mark.parametrize('mode,subdir', [('large', r6.SCOPE), ('r3', r6.LARGE_SCOPE)])
def test_mode_scope_lock(tmp_path, mode, subdir):
    args, mount = make_large_run(tmp_path)
    args.mode, args.source_subdir = mode, subdir
    with pytest.raises(r6.argparse.ArgumentTypeError, match='hard locked'):
        r6.run(args, mount_resolver=lambda _: mount)
    assert not Path(args.out).exists()


def test_large_sampling_rejected_before_io(tmp_path):
    args, mount = make_large_run(tmp_path)
    args.lr_sample = '3'
    with pytest.raises(ValueError, match='sampling is not supported'):
        r6.run(args, mount_resolver=lambda _: mount)
    assert not Path(args.out).exists()
