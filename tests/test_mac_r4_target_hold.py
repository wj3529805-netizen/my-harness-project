"""Synthetic target-removal tests; no physical volumes are accessed."""
import json
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_mac_r3_r4_logic as base
import r4_unplug as r4
from r_common import assert_clean, snapshot_tree


def wait_for_marker(path, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError): pass
        time.sleep(.005)
    pytest.fail(f'Marker did not appear: {path.name}')


# Inject a destination write error only in the test child, after simulated removal.
# The parent retry uses the ordinary copier, and the source is never modified.
TARGET_ERROR_CHILD = '''
import errno, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'scripts/mac'))
import r4_unplug as r4
args = json.loads(sys.argv[1])
gone = Path(args['test_only_gone_flag_file'])
class Writer:
    def __init__(self, stream): self.stream = stream
    def write(self, data):
        if gone.exists(): raise OSError(errno.EIO, 'simulated target write failure')
        return self.stream.write(data)
    def __getattr__(self, name): return getattr(self.stream, name)
    def __enter__(self): self.stream.__enter__(); return self
    def __exit__(self, *args): return self.stream.__exit__(*args)
class Proxy(r4.CopierOSProxy):
    def fdopen(self, fd, mode, *args, **kwargs):
        stream = super().fdopen(fd, mode, *args, **kwargs)
        return Writer(stream) if mode == 'wb' else stream
r4.CopierOSProxy = Proxy
if sys.argv[2] in ('no-partial', 'missing-hold-proof'):
    class MissingReleasePart(r4.Hold):
        def part_size(self):
            return None if gone.exists() else super().part_size()
        def write(self):
            if sys.argv[2] == 'missing-hold-proof' and self.state.get('released_at'):
                self.state['part_size_at_hold_start'] = None
            super().write()
    r4.Hold = MissingReleasePart
sys.exit(r4.child(**args))
'''


@pytest.mark.parametrize('release_evidence', ['partial', 'no-partial', 'missing-hold-proof'])
def test_target_hold_removal_and_strict_recovery(tmp_path, monkeypatch, release_evidence):
    import cetacea.lightroom  # Resolve imports before replacing Popen.

    card, folder, out, args = base.make_throttled_run(tmp_path, 'target-unplug')
    target = Path(args.target_base)
    args.target_volume_uuid = 'target-uuid'
    args.hold_mid_file = True
    args.poll_interval = .005
    args.test_only_gone_flag_file = str(tmp_path / 'target-gone')
    before = snapshot_tree(folder)
    gone = Path(args.test_only_gone_flag_file)
    errors = []
    launched = []
    real_launch = r4.subprocess.Popen
    original_parts = r4.part_sizes
    monkeypatch.setattr(r4, 'target_home_device', lambda home: -1)
    # All synthetic folders share one device; model a separate destination device.
    monkeypatch.setattr(r4, 'target_st_dev', lambda path: path.stat().st_dev + 10)

    def resolver(uuid):
        if uuid == 'fake': return card
        assert uuid == 'target-uuid'
        if gone.exists(): raise RuntimeError('simulated target removal')
        return target

    def part_sizes(w, task):
        if gone.exists(): raise OSError('simulated inaccessible target')
        return original_parts(w, task)

    def launch(command, *a, **kw):
        child_args = json.loads(command[-1])
        assert child_args['target_mount'] == str(target)
        assert child_args['target_uuid'] == 'target-uuid'
        proc = real_launch([sys.executable, '-c', TARGET_ERROR_CHILD,
                            command[-1], release_evidence], *a, **kw)
        launched.append((proc, Path(child_args['home'])))
        return proc

    monkeypatch.setattr(r4.subprocess, 'Popen', launch)
    monkeypatch.setattr(r4, 'part_sizes', part_sizes)

    def simulate():
        try:
            cue = wait_for_marker(out / 'TARGET_UNPLUG_NOW')
            proc, home = launched[0]
            assert cue['held'] and 0 < cue['part_size'] < 6_000_000
            assert proc.poll() is None
            held = json.loads((home / 'hold-state.json').read_text())
            assert held['engaged'] and held['released_by'] is None
            assert held['part_size_at_hold_start'] == cue['part_size']
            # A held .part remains stable until the destination is removed.
            time.sleep(.05)
            assert json.loads((home / 'hold-state.json').read_text())['released_by'] is None
            gone.touch()
            wait_for_marker(out / 'TARGET_REINSERT_NOW')
            gone.unlink()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=simulate)
    worker.start()
    try:
        result = r4.run(args, resolver, base.approve, base.expire_lease)
    finally:
        worker.join(timeout=20)
    assert not worker.is_alive()
    assert not errors, errors
    assert result['status'] == ('FAIL_UNVERIFIED_INTERRUPTION' if release_evidence == 'missing-hold-proof' else 'PASS'), result
    assert result['final_state'] == 'COMPLETED'
    assert result['hold_engaged'] and result['hold_result'] == 'HELD_AND_REMOVED'
    assert result['hold_released_by'] in ('target-removed', 'parent-release')
    assert result['part_in_progress_at_interruption'] is (release_evidence != 'missing-hold-proof')
    assert result['held_file_failed_first'] and result['first_failed_error_class'] == 'EIO'
    assert result['child_exit_code'] != 0
    assert result['source_remained_mounted'] and result['home_outside_target']
    assert snapshot_tree(folder) == before
    assert not (out / 'PULL_NOW').exists() and not (out / 'REINSERT_NOW').exists()
    hold = json.loads((out / 'hold-state.json').read_text())
    if release_evidence == 'no-partial':
        assert hold['part_size_at_release'] is None
        assert result['part_size_at_removal'] == hold['part_size_at_hold_start']
        assert result['part_evidence_source'] == 'held_at_cue_before_target_removal'
    else:
        assert hold['part_size_at_release'] == result['part_size_at_removal']
    if release_evidence == 'missing-hold-proof':
        assert hold['part_size_at_hold_start'] is None
        assert result['notes']
    interruption = json.loads((out / 'interruption-state.json').read_text())
    assert any(asset.get('error', '').startswith('EIO ') for asset in interruption['assets'])
    assert all(item['ok'] for item in json.loads((out / 'final-readback.json').read_text()))
    for path in out.iterdir(): assert_clean(path)


def test_target_hold_probe_checks_target_identity_and_mount(tmp_path, monkeypatch):
    card = tmp_path / 'card'; card.mkdir()
    target = tmp_path / 'target'; target.mkdir()
    other = tmp_path / 'other'; other.mkdir()
    home = tmp_path / 'home'; home.mkdir()
    probes = []
    requested = []
    mounted = True
    resolved = target

    def resolver(uuid):
        requested.append(uuid)
        assert uuid == 'target-uuid'
        if resolved is None: raise RuntimeError('target absent')
        return resolved

    class CaptureHold:
        def __init__(self, home, watch_dir, timeout, probe, removal_reason='card-removed'):
            probes.append(probe)
            assert removal_reason == 'target-removed'

    class Workbench:
        def __init__(self, *a, **kw): pass
        def execute(self, task_id): return {'state': 'COMPLETED'}

    monkeypatch.setattr(r4, 'Hold', CaptureHold)
    monkeypatch.setattr(r4, 'Workbench', Workbench)
    monkeypatch.setattr(r4, 'guard_writes', lambda *a: nullcontext())
    monkeypatch.setattr(r4, 'resolve_mount_by_uuid', resolver)
    monkeypatch.setattr(r4.os.path, 'ismount', lambda path: mounted if Path(path) == target else False)
    import cetacea.ingest.copier as copier
    monkeypatch.setattr(copier, 'os', copier.os)  # Restore child's proxy assignment at teardown.
    assert r4.child(str(home), 'task', str(target), str(card), 0, 8,
                    hold_mid_file=True, watch_dir=str(target),
                    target_mount=str(target), target_uuid='target-uuid') == 0
    probe = probes[0]
    assert probe() is False  # The ordinary directory standing in for the card is not a mount.
    resolved = other
    assert probe() is True
    resolved = None
    assert probe() is True
    resolved = target; mounted = False
    assert probe() is True
    mounted = True
    real_stat = Path.stat
    monkeypatch.setattr(Path, 'stat', lambda path, *a, **kw:
                        SimpleNamespace(st_dev=real_stat(path).st_dev + 1)
                        if path == target else real_stat(path, *a, **kw))
    assert probe() is True
    assert requested and set(requested) == {'target-uuid'}
