"""MOCK daily registration and process-death recovery; NOT real Lightroom."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from cetacea.lightroom import RealLightroomMcpAdapter


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/mac/register_import_to_lr.py'
FAKE = Path(__file__).with_name('fake_lightroom_mcp.py')


@pytest.fixture
def daily():
    spec = importlib.util.spec_from_file_location('daily_import_lr_mock_tests', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_photos(tmp_path, count=30):
    folder = tmp_path / 'MOCK-imported-project'
    folder.mkdir()
    for index in range(count):
        (folder / f'MOCK-{index:03}.NEF').write_bytes(f'MOCK raw {index}'.encode())
    return folder


def adapter(state, *, crash=False):
    command = [sys.executable, str(FAKE), '--catalog-state', str(state)]
    if crash:
        command += ['--crash-batch', '2', '--crash-after', '4']
    return RealLightroomMcpAdapter(test_command=command, batch_size=10, backoff_schedule=[])


def arguments(folder, report, *extra):
    return ['--folder', str(folder), '--catalog', str(folder.parent / 'MOCK-only.lrcat'),
            '--batch-size', '10', '--report', str(report), *extra]


def matching_guard(catalog, **kwargs):
    return {'matches_expected': True, 'open_lrcat_count': 1, 'process_count': 1}


def read_report(path):
    result = json.loads(path.read_text())
    assert result['marker'] == 'CETACEA-MOCK'
    return result


def catalog_rows(state):
    if not state.exists():
        return []
    with sqlite3.connect(state) as connection:
        assert connection.execute("SELECT value FROM mock_control WHERE name = 'marker'").fetchone() == ('CETACEA-MOCK',)
        return connection.execute('SELECT path FROM mock_photos ORDER BY path').fetchall()


def test_daily_three_batches_then_rerun_is_existing(daily, tmp_path):
    folder = make_photos(tmp_path)
    state = tmp_path / 'MOCK-catalog.sqlite'
    first_path, second_path = tmp_path / 'first.json', tmp_path / 'second.json'
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}

    assert daily.main(arguments(folder, first_path, '--execute'), adapter=adapter(state), guard=matching_guard) == 0
    first = read_report(first_path)
    assert first['status'] == 'COMPLETED'
    assert first['total'] == 30
    assert first['counts'] == {'added': 30, 'existing': 0, 'failed': 0, 'pending': 0}
    assert [batch['size'] for batch in first['batches']] == [10, 10, 10]
    assert [batch['status'] for batch in first['batches']] == ['completed'] * 3
    with sqlite3.connect(state) as connection:
        assert connection.execute('SELECT requested, complete FROM mock_batches ORDER BY id').fetchall() == [(10, 1)] * 3

    assert daily.main(arguments(folder, second_path, '--execute'), adapter=adapter(state), guard=matching_guard) == 0
    second = read_report(second_path)
    assert second['counts'] == {'added': 0, 'existing': 30, 'failed': 0, 'pending': 0}
    rows = catalog_rows(state)
    assert len(rows) == len(set(rows)) == 30
    assert {row[0] for row in rows} == {str(p) for p in folder.iterdir()}
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}


def test_daily_second_batch_process_death_resumes_missing_only(daily, tmp_path):
    folder = make_photos(tmp_path)
    state = tmp_path / 'MOCK-catalog.sqlite'
    first_path, second_path = tmp_path / 'interrupted.json', tmp_path / 'resumed.json'

    assert daily.main(arguments(folder, first_path, '--execute'), adapter=adapter(state, crash=True), guard=matching_guard) == 1
    first = read_report(first_path)
    assert first['status'] == 'INCOMPLETE'
    assert first['counts'] == {'added': 10, 'existing': 0, 'failed': 10, 'pending': 10}
    assert [batch['status'] for batch in first['batches']] == ['completed', 'incomplete', 'not_attempted']
    assert len(catalog_rows(state)) == 14
    with sqlite3.connect(state) as connection:
        assert connection.execute('SELECT requested, complete FROM mock_batches ORDER BY id').fetchall() == [(10, 1), (10, 0)]
        assert connection.execute("SELECT value FROM mock_control WHERE name = 'crashed'").fetchone() == ('CETACEA-MOCK',)

    # A new adapter starts new fake bridge processes against the same MOCK
    # catalog, as a separately rerun command would after Lightroom reopens.
    assert daily.main(arguments(folder, second_path, '--execute'), adapter=adapter(state, crash=True), guard=matching_guard) == 0
    resumed = read_report(second_path)
    assert resumed['status'] == 'COMPLETED'
    assert resumed['counts'] == {'added': 16, 'existing': 14, 'failed': 0, 'pending': 0}
    assert resumed['counts']['existing'] + resumed['counts']['added'] == 30
    rows = catalog_rows(state)
    assert len(rows) == len(set(rows)) == 30
    assert {row[0] for row in rows} == {str(p) for p in folder.iterdir()}
    with sqlite3.connect(state) as connection:
        assert connection.execute('SELECT COUNT(*) FROM mock_batches WHERE complete = 0').fetchone() == (1,)


def test_daily_catalog_mismatch_never_writes_a_batch(daily, tmp_path):
    folder = make_photos(tmp_path)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'blocked.json'
    calls = []

    def mismatch(catalog, **kwargs):
        calls.append(catalog)
        return {'matches_expected': False, 'open_lrcat_count': 1, 'process_count': 1}

    assert daily.main(arguments(folder, report, '--execute'), adapter=adapter(state), guard=mismatch) == 1
    assert calls
    assert catalog_rows(state) == []
    assert read_report(report)['counts']['added'] == 0


def test_daily_catalog_switch_before_second_batch_stops_remaining(daily, tmp_path):
    folder = make_photos(tmp_path)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'switched.json'

    def switched(catalog, **kwargs):
        # The fake database is created only when the first batch starts.
        # Once that batch has committed, emulate switching the opened catalog.
        return {'matches_expected': len(catalog_rows(state)) == 0}

    assert daily.main(arguments(folder, report, '--execute'), adapter=adapter(state), guard=switched) == 1
    assert len(catalog_rows(state)) == 10
    result = read_report(report)
    assert result['counts']['added'] == 10
    assert result['counts']['existing'] == 0


@pytest.mark.parametrize('explicit', [False, True])
def test_daily_dry_run_never_starts_bridge_or_checks_lr(daily, tmp_path, explicit):
    folder = make_photos(tmp_path)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'dry.json'

    def forbidden(*args, **kwargs):
        raise AssertionError('MOCK dry-run must not inspect Lightroom or invoke MCP')

    mock_adapter = adapter(state)
    mock_adapter.register = forbidden
    opts = ['--dry-run'] if explicit else []
    assert daily.main(arguments(folder, report, *opts), adapter=mock_adapter, guard=forbidden) == 0
    result = read_report(report)
    assert result['status'] == 'DRY_RUN'
    assert result['total'] == 30
    assert result['counts']['added'] == result['counts']['existing'] == result['counts']['failed'] == 0
    assert not state.exists()


@pytest.mark.parametrize('include,expected', [('raw', 2), ('jpg', 2), ('all', 4)])
def test_daily_recursive_filters_exclusions_and_overlapping_roots(daily, tmp_path, include, expected):
    folder = make_photos(tmp_path, count=1)
    nested = folder / 'nested'
    nested.mkdir()
    (nested / 'MOCK.RAF').write_bytes(b'MOCK raw')
    (nested / 'MOCK.JPG').write_bytes(b'MOCK jpg')
    (folder / 'MOCK.jpeg').write_bytes(b'MOCK jpeg')
    (folder / 'MOCK.xmp').write_bytes(b'MOCK sidecar unchanged')
    (folder / '._MOCK.NEF').write_bytes(b'MOCK AppleDouble excluded')
    for name in ('proof', 'proofs', 'preview', 'previews', '预览', '预览图', 'custom-exclude'):
        directory = folder / name
        directory.mkdir()
        (directory / 'MOCK.NEF').write_bytes(b'MOCK excluded raw')
        (directory / 'MOCK.JPG').write_bytes(b'MOCK excluded jpg')
    external = tmp_path / 'MOCK-symlink-target.NEF'
    external.write_bytes(b'MOCK do not follow')
    (folder / 'MOCK-link.NEF').symlink_to(external)
    (folder / 'MOCK-link-dir').symlink_to(nested, target_is_directory=True)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'selected.json'

    argv = arguments(folder, report, '--include', include, '--folder', str(nested),
                     '--exclude-dir', 'custom-exclude')
    assert daily.main(argv, adapter=adapter(state), guard=matching_guard) == 0
    assert read_report(report)['total'] == expected
    assert not state.exists()
    assert (folder / 'MOCK.xmp').read_bytes() == b'MOCK sidecar unchanged'


def test_daily_refuses_existing_report_before_catalog_write(daily, tmp_path):
    folder = make_photos(tmp_path)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'keep.json'
    original = b'{"MOCK": "keep previous evidence"}\n'
    report.write_bytes(original)
    assert daily.main(arguments(folder, report, '--execute'), adapter=adapter(state), guard=matching_guard) != 0
    assert report.read_bytes() == original
    assert catalog_rows(state) == []


def test_daily_cli_default_dry_run_needs_no_runtime_or_lr(tmp_path):
    folder = make_photos(tmp_path, count=2)
    report = tmp_path / 'cli-dry.json'
    result = subprocess.run([sys.executable, str(SCRIPT), *arguments(folder, report)],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(report.read_text())
    assert payload['status'] == 'DRY_RUN'
    assert payload['total'] == 2
    assert '2' in result.stdout


@pytest.mark.parametrize('batch_size', ['0', '-1', '201'])
def test_daily_rejects_invalid_batch_size_before_any_lr_access(daily, tmp_path, batch_size):
    folder = make_photos(tmp_path, count=1)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'invalid.json'
    argv = arguments(folder, report, '--batch-size', batch_size, '--execute')
    with pytest.raises(SystemExit) as error:
        daily.main(argv, adapter=adapter(state), guard=matching_guard)
    assert error.value.code != 0
    assert catalog_rows(state) == []


@pytest.mark.parametrize('subdir', ['', 'proofs'])
def test_daily_report_inside_input_is_rejected_without_creating_files(daily, tmp_path, subdir):
    folder = make_photos(tmp_path, count=1)
    parent = folder / subdir if subdir else folder
    if subdir:
        parent.mkdir()
    report = parent / 'MOCK-must-not-write.json'
    state = tmp_path / 'MOCK-catalog.sqlite'
    assert daily.main(arguments(folder, report, '--execute'), adapter=adapter(state), guard=matching_guard) == 1
    assert not report.exists()
    assert catalog_rows(state) == []


def test_daily_symlinked_input_parent_is_rejected(daily, tmp_path):
    folder = make_photos(tmp_path, count=1)
    real_parent = tmp_path / 'MOCK-real-parent'
    real_parent.mkdir()
    real_folder = real_parent / 'MOCK-project'
    real_folder.mkdir()
    (real_folder / 'MOCK.NEF').write_bytes(b'MOCK raw')
    linked_parent = tmp_path / 'MOCK-linked-parent'
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    state, report = tmp_path / 'MOCK-catalog.sqlite', tmp_path / 'input-link.json'
    argv = arguments(linked_parent / real_folder.name, report, '--execute')
    assert daily.main(argv, adapter=adapter(state), guard=matching_guard) == 1
    assert catalog_rows(state) == []
    assert (real_folder / 'MOCK.NEF').read_bytes() == b'MOCK raw'


def test_daily_existing_report_symlink_is_not_followed(daily, tmp_path):
    folder = make_photos(tmp_path, count=1)
    state = tmp_path / 'MOCK-catalog.sqlite'
    original = tmp_path / 'MOCK-keep.json'
    original.write_text('MOCK keep evidence\n')
    report = tmp_path / 'MOCK-report-link.json'
    report.symlink_to(original)
    assert daily.main(arguments(folder, report, '--execute'), adapter=adapter(state), guard=matching_guard) == 1
    assert report.is_symlink()
    assert original.read_text() == 'MOCK keep evidence\n'
    assert catalog_rows(state) == []


def test_daily_missing_runtime_stops_before_catalog_probe(daily, tmp_path, monkeypatch, capsys):
    folder = make_photos(tmp_path, count=1)
    report = tmp_path / 'missing-runtime.json'
    root = tmp_path / 'MOCK-empty-checkout'
    root.mkdir()
    monkeypatch.setattr(daily, 'ROOT', root)

    def forbidden(*args, **kwargs):
        raise AssertionError('MOCK missing runtime must fail before a Lightroom process query')

    assert daily.main(arguments(folder, report, '--execute'), guard=forbidden) == 1
    result = json.loads(report.read_text())
    assert result['status'] == 'FAILED'
    assert result['counts']['added'] == 0
    assert 'prepare_lightroom_batch.py' in result['error']
    assert 'prepare_lightroom_batch.py' in capsys.readouterr().err
