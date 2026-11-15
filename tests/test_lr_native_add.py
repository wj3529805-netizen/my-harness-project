"""Offline MOCK only: fixture preferences, fake MCP, and deterministic clock."""
from contextlib import contextmanager
import json
from pathlib import Path
import plistlib
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/mac'))
import lr_native_add as native
import bench_lr_add as bench
from cetacea.lightroom import RealLightroomMcpAdapter

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/lr_native_safe_prefs.plist'


@pytest.fixture(autouse=True)
def never_real_prefs(monkeypatch):
    def forbidden():
        raise AssertionError('MOCK tests must inject fixture prefs, never read real preferences')
    monkeypatch.setattr(native, 'read_prefs', forbidden)


def prefs():
    return native.parse_prefs(FIXTURE.read_bytes())


class Clock:
    now = 0
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class FakeMcp:
    testing = True
    profile_events = []
    def __init__(self, *, polls=2, existing=(), extras=()):
        self.stored = set(existing)
        self.extra = set(extras)
        self.polls = polls
        self.after = 0
        self.triggered = False
        self.calls = []
        self.entered = 0
    @contextmanager
    def _connection(self):
        self.entered += 1
        yield
    def call_tool(self, name, args, **kwargs):
        self.calls.append((name, args))
        if name.startswith('native_add_folder'):
            self.triggered = True
            self.expected = set(args['expected_files'])
            return dict(success=True, triggered=True, started_at=1.0, marker='CETACEA-MOCK')
        assert name == 'catalog_paths_present'
        if self.triggered:
            self.after += 1
            if self.polls is not None and self.after >= self.polls:
                self.stored |= self.expected | self.extra
        result = dict(success=True, present=[p for p in args['paths'] if p in self.stored],
                      missing=[p for p in args['paths'] if p not in self.stored])
        if 'folder_path' in args:
            result['folder_paths'] = sorted(p for p in self.stored if Path(p).is_relative_to(args['folder_path']))
        return result


def setup(tmp_path, count=2):
    folder = tmp_path / 'MOCK-photos'
    folder.mkdir()
    paths = []
    for i in range(count):
        path = folder / f'{i}.NEF'
        path.write_bytes(b'MOCK RAW, no real photograph')
        paths.append(str(path))
    opts = ['--catalog', str(tmp_path / 'MOCK-test.lrcat'), '--folder', str(folder),
            '--i-checked-import-settings', '--poll-seconds', '1', '--timeout-seconds', '3']
    return folder, paths, opts


def invoke(tmp_path, opts, instance, *, report='report.json', reader=prefs, guard=None, execute=True):
    clock = Clock()
    target = tmp_path / report
    code = native.main([*opts, '--report', str(target), *(['--execute'] if execute else [])],
                       adapter=instance, guard=guard or (lambda *a, **k: {'matches_expected': True}),
                       prefs_reader=reader, clock=clock, sleep=clock.sleep)
    return code, json.loads(target.read_text())


def test_parse_fixture_export_and_binary():
    expected = prefs()
    assert native.parse_prefs(plistlib.dumps(expected, fmt=plistlib.FMT_BINARY)) == expected
    calls = []
    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return type('Result', (), {'stdout': FIXTURE.read_bytes()})()
    assert native.read_prefs.__name__ == 'forbidden'  # autouse prevents accidental real use
    # Test the original read function via a fresh module, still with injected runner.
    import importlib.util
    spec = importlib.util.spec_from_file_location('native_prefs_fixture_only', ROOT / 'scripts/mac/lr_native_add.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.read_prefs(runner=runner) == expected
    assert calls[0][0] == ['defaults', 'export', native.DOMAIN, '-']
    assert calls[0][1]['capture_output'] is True


@pytest.mark.parametrize('key', native.SAFE_PREFS)
@pytest.mark.parametrize('missing', [False, True])
def test_each_unsafe_or_missing_preference_refused(tmp_path, key, missing):
    _, _, opts = setup(tmp_path)
    unsafe = prefs()
    if missing:
        del unsafe[key]
    else:
        unsafe[key] = 1 if native.SAFE_PREFS[key] == 0 else 'MOCK-unsafe'
    instance = FakeMcp()
    code, report = invoke(tmp_path, opts, instance, reader=lambda: unsafe)
    assert code == 1 and key in report['error'] and not instance.calls and not instance.entered


def test_unknown_dng_requires_flag_and_no_override_unsafe(tmp_path):
    _, _, opts = setup(tmp_path)
    opts.remove('--i-checked-import-settings')
    code, report = invoke(tmp_path, opts, FakeMcp())
    assert code == 1 and 'UNVERIFIED' in report['error']
    assert 'key unknown' in report['error']


@pytest.mark.parametrize('relative', ['extra.JPG', 'previews/p.JPG', 'previews/p.NEF',
                                      '.hidden/p.NEF', '.hidden.JPG', 'clip.mov', 'other.png'])
def test_extra_file_refusal_even_excluded_or_hidden(tmp_path, relative, capsys):
    folder, _, opts = setup(tmp_path)
    extra = folder / relative
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b'MOCK extra')
    instance = FakeMcp()
    code, report = invoke(tmp_path, opts, instance)
    assert code == 1 and report['extra_importable_files'] == [str(extra)]
    assert str(extra) in capsys.readouterr().out and not instance.calls


def test_selection_poll_completion_extras_and_idempotency(tmp_path):
    folder, paths, opts = setup(tmp_path)
    (folder / '._0.NEF').write_bytes(b'MOCK AppleDouble')
    extra = str(folder / 'extra.JPG')
    (folder / 'extra.JPG').write_bytes(b'MOCK JPG')
    existing_extra = str(folder / 'no-longer-on-disk.JPG')
    instance = FakeMcp(existing=[paths[0], existing_extra], extras=[extra])
    code, report = invoke(tmp_path, [*opts, '--allow-extra'], instance)
    assert code == 0 and report['marker'] == 'CETACEA-MOCK'
    assert report['counts'] == dict(present=2, missing=0, existing=1, newly_present=1)
    assert report['native_wall_seconds'] == 1 and report['native_seconds_per_photo'] == 0.5
    assert report['extra_adds'] == [extra]
    assert report['extra_catalog_paths'] == sorted([extra, existing_extra])
    assert report['settings']['dng_conversion'] == 'UNVERIFIED'
    assert instance.entered == 1
    code, report = invoke(tmp_path, [*opts, '--allow-extra'], instance, report='rerun.json')
    assert code == 0 and report['counts']['existing'] == 2
    assert report['counts']['newly_present'] == 0 and report['extra_adds'] == []
    assert report['native_seconds_per_new_photo'] is None


def test_timeout_keeps_missing_and_no_retry(tmp_path):
    _, paths, opts = setup(tmp_path)
    instance = FakeMcp(polls=None, existing=[paths[0]])
    code, report = invoke(tmp_path, opts, instance)
    assert code == 1 and report['status'] == 'TIMEOUT'
    assert report['native_wall_seconds'] == 3 and report['missing_paths'] == paths[1:]
    assert report['counts']['missing'] == 1
    assert len([name for name, _ in instance.calls if name == 'native_add_folder']) == 1


def test_ui_variant_and_default_dry_run(tmp_path):
    _, _, opts = setup(tmp_path)
    instance = FakeMcp()
    code, report = invoke(tmp_path, opts, instance, execute=False)
    assert code == 0 and report['status'] == 'DRY_RUN' and not instance.calls and not instance.entered
    code, report = invoke(tmp_path, [*opts, '--ui'], instance, report='ui.json')
    assert code == 0 and report['registration_mode'] == 'native-ui'
    assert 'native_add_folder_ui' in [name for name, _ in instance.calls]


def test_catalog_guard_and_changed_prefs_stop_before_trigger(tmp_path):
    _, _, opts = setup(tmp_path)
    instance = FakeMcp()
    code, report = invoke(tmp_path, opts, instance, guard=lambda *a, **k: {'matches_expected': False})
    assert code == 1 and not instance.calls and not instance.entered
    reads = []
    def reader():
        data = prefs()
        if reads:
            data['AgImport_importBehavior'] = 'move'
        reads.append(True)
        return data
    code, report = invoke(tmp_path, opts, instance, reader=reader, report='changed.json')
    assert code == 1 and all(name == 'catalog_paths_present' for name, _ in instance.calls)


def test_scan_recursive_limits_and_symlinks(tmp_path):
    folder, _, _ = setup(tmp_path)
    child = folder / 'nested'
    child.mkdir()
    (child / 'x.NEF').write_bytes(b'MOCK')
    with pytest.raises(native.Error, match='recursive'):
        native.inventory(folder, False)
    assert len(native.inventory(folder, True)[0]) == 3
    (folder / 'alias').symlink_to(child)
    with pytest.raises(native.Error, match='symlinks'):
        native.inventory(folder, True)


def test_batch_presence_500_bound_and_exact_response(tmp_path):
    folder, paths, opts = setup(tmp_path, 501)
    instance = FakeMcp(polls=1)
    code, report = invoke(tmp_path, opts, instance)
    assert code == 0 and report['counts']['present'] == 501
    assert max(len(args['paths']) for name, args in instance.calls if name == 'catalog_paths_present') == 500
    assert sum('folder_path' in args for name, args in instance.calls if name == 'catalog_paths_present') == 2
    instance = FakeMcp()
    instance.call_tool = lambda *a: dict(success=True, present=paths[:1], missing=[])
    code, report = invoke(tmp_path, opts, instance, report='bad-response.json')
    assert code == 1 and 'Invalid exact-path' in report['error']


@pytest.mark.parametrize('mode', ['baseline', 'fast', 'native'])
def test_bench_production_refusal_all_modes(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'MOCK-home'))
    with pytest.raises(SystemExit) as error:
        bench.main(['--mode', mode, '--catalog', str(Path.home() / 'Pictures/Lightroom/TEST.lrcat'),
                    '--folder', str(tmp_path), '--report', str(tmp_path / 'no.json')])
    assert error.value.code == 2 and not (tmp_path / 'no.json').exists()


def test_bench_native_dispatch_and_real_fake_mcp_protocol(tmp_path):
    _, _, opts = setup(tmp_path)
    instance = RealLightroomMcpAdapter(test_command=[sys.executable, str(ROOT / 'tests/fake_lightroom_mcp.py')],
                                        backoff_schedule=[], activate_hook=None)
    target = tmp_path / 'bench-native.json'
    assert bench.main([*opts, '--mode', 'native', '--execute', '--report', str(target)], adapter=instance,
                      guard=lambda *a, **k: {'matches_expected': True}, prefs_reader=prefs) == 0
    report = json.loads(target.read_text())
    assert report['marker'] == 'CETACEA-MOCK' and report['counts']['present'] == 2
    assert report['registration_mode'] == 'native'


def test_report_never_overwrites_or_writes_inside_source(tmp_path):
    folder, _, opts = setup(tmp_path)
    target = tmp_path / 'keep.json'
    target.write_text('MOCK KEEP')
    assert native.main([*opts, '--report', str(target)], prefs_reader=prefs) == 1
    assert target.read_text() == 'MOCK KEEP'
    assert native.main([*opts, '--report', str(folder / 'no.json')], prefs_reader=prefs) == 1
    assert not (folder / 'no.json').exists()


@pytest.mark.parametrize('count', [0, 2001])
def test_native_expected_count_limits(tmp_path, count):
    folder, _, _ = setup(tmp_path, count)
    with pytest.raises(native.Error, match='1..2000'):
        native.inventory(folder, True)


def test_standalone_explicit_production_catalog_allowed_only_with_matching_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'MOCK-home'))
    _, _, opts = setup(tmp_path)
    production = str(Path.home() / 'Pictures/Lightroom/Production.lrcat')
    opts[1] = production  # string only: never create/stat/open a .lrcat
    seen = []
    def guard(expected, **kwargs):
        seen.append(expected)
        return {'matches_expected': expected == production}
    code, report = invoke(tmp_path, opts, FakeMcp(), guard=guard)
    assert code == 0 and seen and all(value == production for value in seen)
    code, report = invoke(tmp_path, opts, FakeMcp(), report='wrong-catalog.json',
                          guard=lambda *a, **k: {'matches_expected': False})
    assert code == 1


def test_guard_changes_after_trigger_stops_polling_without_retrigger(tmp_path):
    _, _, opts = setup(tmp_path)
    instance = FakeMcp()
    def guard(*args, **kwargs):
        return {'matches_expected': not instance.triggered}
    code, report = invoke(tmp_path, opts, instance, guard=guard)
    assert code == 1 and report['status'] == 'FAILED'
    assert len([name for name, _ in instance.calls if name.startswith('native_add_folder')]) == 1


def test_deadline_caps_inflight_poll_request(tmp_path):
    _, _, opts = setup(tmp_path)
    instance = FakeMcp(polls=None)
    original = instance.call_tool
    clock = Clock()
    budgets = []
    def call(name, args, **kwargs):
        if name == 'catalog_paths_present' and 'timeout_seconds' in kwargs:
            budgets.append(kwargs['timeout_seconds'])
            clock.now += kwargs['timeout_seconds']
            raise RuntimeError('MOCK in-flight deadline')
        return original(name, args, **kwargs)
    instance.call_tool = call
    target = tmp_path / 'deadline.json'
    assert native.main([*opts, '--execute', '--report', str(target)], adapter=instance,
                       guard=lambda *a, **k: {'matches_expected': True}, prefs_reader=prefs,
                       clock=clock, sleep=clock.sleep) == 1
    report = json.loads(target.read_text())
    assert budgets == [3] and report['status'] == 'TIMEOUT'
    assert report['native_wall_seconds'] == 3


def test_final_snapshot_cannot_claim_success_when_expected_disappears(tmp_path):
    _, _, opts = setup(tmp_path)
    instance = FakeMcp(polls=1)
    original = instance.call_tool
    def call(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == 'catalog_paths_present' and instance.triggered and 'folder_path' in args:
            result['present'] = []
            result['missing'] = args['paths']
        return result
    instance.call_tool = call
    code, report = invoke(tmp_path, opts, instance)
    assert code == 1 and report['status'] == 'INCOMPLETE'
    assert report['counts']['present'] == 0 and report['counts']['missing'] == 2
