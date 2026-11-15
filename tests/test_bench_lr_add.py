"""MOCK benchmark safety and dispatch; never open a real Lightroom catalog."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from cetacea.lightroom import RealLightroomMcpAdapter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench_lr_add_tests', ROOT / 'scripts/mac/bench_lr_add.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


@pytest.mark.parametrize('suffix', ['Lightroom Catalog.lrcat', 'nested/Test.lrcat', '../Lightroom/Test.lrcat'])
def test_bench_refuses_production_catalog_before_any_action(tmp_path, monkeypatch, suffix):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'MOCK-home'))
    def forbidden(*args, **kwargs):
        raise AssertionError('MOCK production path must be rejected before dispatch')
    monkeypatch.setattr(bench.register, 'main', forbidden)
    with pytest.raises(SystemExit) as error:
        bench.main(['--catalog', str(Path.home() / 'Pictures/Lightroom' / suffix),
                    '--folder', str(tmp_path), '--mode', 'fast', '--report', str(tmp_path / 'no.json')])
    assert error.value.code == 2
    assert not (tmp_path / 'no.json').exists()


def test_bench_rejects_symlink_parent(tmp_path):
    (tmp_path / 'real').mkdir()
    (tmp_path / 'alias').symlink_to(tmp_path / 'real', target_is_directory=True)
    with pytest.raises(Exception, match='symlink'):
        bench.test_catalog(str(tmp_path / 'alias/Test.lrcat'))


@pytest.mark.parametrize('mode', ['baseline', 'fast'])
def test_bench_default_dry_and_execute_catalog_guard(tmp_path, mode):
    folder = tmp_path / 'MOCK-photos'
    folder.mkdir()
    for i in range(3):
        (folder / f'{i}.NEF').write_bytes(b'MOCK NEF')
    instance = RealLightroomMcpAdapter(test_command=[sys.executable, str(ROOT / 'tests/fake_lightroom_mcp.py')], backoff_schedule=[])
    def forbidden(*args, **kwargs):
        raise AssertionError('MOCK dry run cannot inspect Lightroom')
    opts = ['--catalog', str(tmp_path / 'MOCK-test.lrcat'), '--folder', str(folder), '--mode', mode, '--profile']
    report = tmp_path / 'dry.json'
    assert bench.main([*opts, '--report', str(report)], adapter=instance, guard=forbidden) == 0
    assert json.loads(report.read_text())['profile']['events'] == []
    report = tmp_path / 'blocked.json'
    calls = []
    def mismatch(*args, **kwargs):
        calls.append(True)
        return {'matches_expected': False}
    assert bench.main([*opts, '--report', str(report), '--execute'], adapter=instance, guard=mismatch) == 1
    assert calls and instance.profile_events == []  # guard fails BEFORE bridge spawn
    report = tmp_path / 'execute.json'
    assert bench.main([*opts, '--report', str(report), '--execute'], adapter=instance,
                      guard=lambda *a, **k: {'matches_expected': True}) == 0
    payload = json.loads(report.read_text())
    assert payload['marker'] == 'CETACEA-MOCK'
    assert payload['counts']['added'] == 3
    assert payload['registration_mode'] == mode
    assert payload['seconds_per_photo'] > 0


def test_bench_rejects_leaf_alias_without_opening_catalog(tmp_path):
    # Synthetic alias only, not an actual Lightroom catalog.
    alias = tmp_path / 'MOCK-alias.lrcat'
    alias.symlink_to(tmp_path / 'nonexistent-MOCK-target')
    with pytest.raises(Exception, match='symlink'):
        bench.test_catalog(str(alias))
