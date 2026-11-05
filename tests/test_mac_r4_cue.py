"""Pre-cue failure and stale-observation regressions, using synthetic files only."""
import json
import sys
from pathlib import Path

import pytest
import test_mac_r3_r4_logic as base
import r4_unplug as r4
from r_common import assert_clean


FAILED_CHILD = '''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'scripts/mac'))
import r4_unplug as r4
import cetacea.core as core
class FailedCopy:
    def __init__(self, *args): pass
    def copy(self, source, library, task_id, n, item):
        if n == 0:
            return {'status': 'FAILED', 'error': 'EIO [Errno 5] simulated device error'}
        raise PermissionError('Write outside allowed test roots')
core.CopyEngine = FailedCopy
print('simulated child diagnostic', flush=True)
sys.exit(r4.child(**json.loads(sys.argv[1])))
'''


def target_run(tmp_path, monkeypatch):
    card, folder, out, args = base.make_throttled_run(tmp_path, 'target-unplug')
    args.target_volume_uuid = 'target-uuid'
    target = Path(args.target_base)
    monkeypatch.setattr(r4, 'target_home_device', lambda home: -1)
    monkeypatch.setattr(r4, 'target_st_dev', lambda path: path.stat().st_dev + 10)
    return out, args, lambda uuid: card if uuid == 'fake' else target


@pytest.mark.parametrize('race', ['before-observation', 'stale-observation', 'during-cue-check'])
def test_target_child_failure_before_cue_is_honest(tmp_path, monkeypatch, capsys, race):
    import cetacea.lightroom  # Finish imports before replacing the subprocess launcher.
    out, args, resolver = target_run(tmp_path, monkeypatch)
    launch = r4.subprocess.Popen
    processes = []

    def failed_child(command, *a, **kw):
        proc = launch([sys.executable, '-c', FAILED_CHILD, command[-1]], *a, **kw)
        processes.append(proc)
        return proc

    def observed(proc, w, task, *a):
        if race != 'during-cue-check': proc.wait(timeout=15)
        return False if race == 'before-observation' else {'stale/0.part': 1024}

    def cue_parts(w, task):
        processes[0].wait(timeout=15)
        return [{'path': 'stale/0.part', 'size': 1024}]

    monkeypatch.setattr(r4.subprocess, 'Popen', failed_child)
    monkeypatch.setattr(r4, 'observe_copy', observed)
    if race == 'during-cue-check': monkeypatch.setattr(r4, 'part_sizes', cue_parts)
    result = r4.run(args, resolver, base.approve)
    assert result['status'] == 'FAIL_STOPPED', result
    assert 'before a valid physical cue' in result['traceback']
    assert 'Write outside allowed test roots' in result['traceback']
    assert 'EIO [Errno 5]' in result['traceback']
    assert 'simulated child diagnostic' in result['traceback']
    assert result['first_failed_file'] == '0.NEF'
    assert result['first_failed_error_class'] == 'EIO'
    assert result['child_exit_code'] == 1
    assert not result['part_in_progress_at_interruption']
    for name in ('TARGET_UNPLUG_NOW', 'TARGET_REINSERT_NOW', 'recover.json', 'retry-result.json'):
        assert not (out / name).exists()
    assert 'NOW UNPLUG' not in capsys.readouterr().out
    interruption = json.loads((out / 'interruption-state.json').read_text())
    assert interruption['task']['state'] == 'FAILED'
    assert interruption['task']['error'] == 'Write outside allowed test roots'
    assert any(a.get('error', '').startswith('EIO ') for a in interruption['assets'])
    for path in out.iterdir(): assert_clean(path)


@pytest.mark.parametrize('size', [None, 0, 6_000_000])
def test_target_rechecks_partial_size_before_cue(tmp_path, monkeypatch, capsys, size):
    import cetacea.lightroom
    out, args, resolver = target_run(tmp_path, monkeypatch)
    monkeypatch.setattr(r4, 'observe_copy', lambda *a: {'stale/0.part': 1024})
    monkeypatch.setattr(r4, 'part_sizes', lambda *a: [] if size is None else [{'path': 'stale/0.part', 'size': size}])
    result = r4.run(args, resolver, base.approve)
    assert result['status'] == 'FAIL_STOPPED', result
    assert 'No live partial file at cue time' in result['traceback']
    assert 'NOW UNPLUG' not in capsys.readouterr().out
    for name in ('TARGET_UNPLUG_NOW', 'TARGET_REINSERT_NOW', 'recover.json', 'retry-result.json'):
        assert not (out / name).exists()


def test_target_child_completed_before_cue_is_stopped(tmp_path, monkeypatch):
    out, args, resolver = target_run(tmp_path, monkeypatch)
    args.throttle_mbps = 1000
    def observed(proc, *a):
        proc.wait(timeout=15)
        return {'stale/0.part': 1024}
    monkeypatch.setattr(r4, 'observe_copy', observed)
    result = r4.run(args, resolver, base.approve)
    assert result['status'] == 'FAIL_STOPPED', result
    assert result['child_exit_code'] == 0
    assert 'before a valid physical cue' in result['traceback']
    assert json.loads((out / 'interruption-state.json').read_text())['task']['state'] == 'COMPLETED'
    for name in ('TARGET_UNPLUG_NOW', 'TARGET_REINSERT_NOW', 'recover.json', 'retry-result.json'):
        assert not (out / name).exists()


def test_observation_does_not_hash_published_files(monkeypatch):
    class Live:
        def poll(self): return None
    values = iter([[{'path': '0.part', 'size': 1024}], [{'path': '0.part', 'size': 2048}]])
    monkeypatch.setattr(r4, 'part_sizes', lambda *a: next(values))
    monkeypatch.setattr(r4, 'files_state', lambda *a: pytest.fail('Published hashes must not delay progress observation'))
    assert r4.observe_copy(Live(), None, None, .001) == {'0.part': 2048}


def test_uncaught_child_error_with_unmapped_path_still_saves_failure(tmp_path, monkeypatch):
    import cetacea.lightroom
    out, args, resolver = target_run(tmp_path, monkeypatch)
    launch = r4.subprocess.Popen
    def failed_child(command, *a, **kw):
        return launch([sys.executable, '-c', "raise RuntimeError('device failure at /Users/private/unmapped')"], *a, **kw)
    monkeypatch.setattr(r4.subprocess, 'Popen', failed_child)
    result = r4.run(args, resolver, base.approve)
    assert result['status'] == 'FAIL_STOPPED'
    assert result['child_exit_code'] == 1
    assert 'RuntimeError: child output withheld' in result['traceback']
    interruption = json.loads((out / 'interruption-state.json').read_text())
    assert 'RuntimeError: child output withheld' in interruption['child_output']
    assert json.loads((out / 'result.json').read_text())['status'] == 'FAIL_STOPPED'
    for name in ('TARGET_UNPLUG_NOW', 'TARGET_REINSERT_NOW', 'recover.json', 'retry-result.json'):
        assert not (out / name).exists()
    for path in out.iterdir(): assert_clean(path)
