import io
import json
import threading
import time
from pathlib import Path

import pytest
import test_mac_r3_r4_logic as base
import r4_unplug as r4
from r_common import assert_clean


@pytest.mark.parametrize('extra, message', [
    (['--hold-mid-file'], 'requires --throttle-mbps'),
    (['--hold-mid-file', '--throttle-mbps', '8', '--scenario', 'kill-process'], 'requires --scenario unplug'),
    (['--hold-mid-file', '--throttle-mbps', '8', '--pull-timeout', '3001'], 'must be <= 3000'),
])
def test_validation(tmp_path, extra, message):
    card = tmp_path / 'card'; card.mkdir()
    args = r4.parser().parse_args(['--source-uuid', 'fake', '--source-subdir', 'test', '--out', str(tmp_path / 'out'), '--confirm-card-readonly'] + extra)
    result = r4.run(args, lambda _: card)
    assert result['status'] == 'FAIL_STOPPED' and message in result['traceback']


def test_reader_hold_and_release(tmp_path):
    part = tmp_path / '0.part'; part.write_bytes(b'x' * 100)
    gone = threading.Event()
    hold = r4.Hold(tmp_path, tmp_path, 2, gone.is_set)
    data = b'a' * (1024 * 1024) + b'end'
    reader = r4.ThrottledReader(io.BytesIO(data), 1000, hold)
    assert reader.read(1024 * 1024) == data[:-3]
    output = []
    worker = threading.Thread(target=lambda: output.append(reader.read(3))); worker.start()
    deadline = time.monotonic() + 2
    while not hold.state['engaged'] and time.monotonic() < deadline: time.sleep(.01)
    assert hold.state['engaged'] and not output and hold.state['part_size_at_hold_start'] == 100
    gone.set(); worker.join(2)
    assert output == [b'end'] and hold.state['released_by'] == 'card-removed'


def test_timeout_and_never_engaged(tmp_path):
    hold = r4.Hold(tmp_path, tmp_path, .1, lambda: False)
    reader = r4.ThrottledReader(io.BytesIO(b'x' * (1024 * 1024) + b'z'), 1000, hold)
    assert len(reader.read(1024 * 1024)) == 1024 * 1024
    assert reader.read(1) == b'z' and hold.state['released_by'] == 'timeout'
    hold = r4.Hold(tmp_path, tmp_path, .1, lambda: False)
    file = tmp_path / 'source'; file.write_bytes(b'x' * 1024 * 1024)
    proxy = r4.CopierOSProxy(1000, hold)
    with proxy.fdopen(r4.os.open(file, r4.os.O_RDONLY), 'rb') as reader:
        assert len(reader.read(1024 * 1024)) == 1024 * 1024
        assert reader.read(1024 * 1024) == b''
    assert not hold.state['engaged'] and hold.state['released_by'] == 'never-engaged'


def test_hold_timeout_end_to_end(tmp_path):
    card, folder, out, args = base.make_throttled_run(tmp_path, 'unplug')
    args.hold_mid_file = True; args.pull_timeout = 2
    args.test_only_gone_flag_file = str(tmp_path / 'gone')
    result = r4.run(args, lambda _: card, base.approve, base.expire_lease)
    assert result['status'] == 'INTERRUPTION_NOT_ACHIEVED', result
    assert result['hold_result'] == 'HOLD_TIMEOUT' and result['hold_engaged']
    assert result['hold_released_by'] == 'timeout'
    assert not (out / 'recover.json').exists()
    captured = json.loads((out / 'after-interruption-files.json').read_text())
    assert len(captured['published']) == 3 and all(item['ok'] for item in captured['published'])
    assert json.loads((out / 'PULL_NOW').read_text())['held']
    for path in out.iterdir(): assert_clean(path)


def test_non_hold_child_exits_before_removal(tmp_path):
    card, folder, out, args = base.make_throttled_run(tmp_path, 'unplug')
    result = r4.run(args, lambda _: card, base.approve)
    assert result['status'] == 'FAIL_STOPPED'
    assert 'Child exited before card removal was observed' in result['traceback']


def make_random_hold_run(tmp_path):
    import random
    card, folder, out, args = base.make_throttled_run(tmp_path, 'unplug')
    rng = random.Random(314159)
    for path in sorted(folder.iterdir()):
        path.write_bytes(rng.randbytes(6_000_000))
    args.hold_mid_file = True
    args.poll_interval = .005
    args.test_only_gone_flag_file = str(tmp_path / 'gone')
    return card, folder, out, args


def wait_for_marker(path, timeout=15):
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert path.exists(), f'Marker did not appear: {path.name}'
    return json.loads(path.read_text())


def test_hold_unplug_real_read_failure_and_recovery(tmp_path):
    import os
    from r_common import snapshot_tree

    started = time.monotonic()
    card, folder, out, args = make_random_hold_run(tmp_path)
    before = snapshot_tree(folder)
    source = folder / '0.NEF'
    original = source.read_bytes()
    stat = source.stat()
    missing = threading.Event()
    errors = []
    gone = Path(args.test_only_gone_flag_file)

    def resolver(_):
        if missing.is_set():
            raise RuntimeError('simulated removal')
        return card

    def simulate():
        try:
            assert wait_for_marker(out / 'PULL_NOW')['held']
            with source.open('r+b') as stream:
                stream.truncate(1024 * 1024)
            missing.set()
            time.sleep(.2)
            gone.touch()
            wait_for_marker(out / 'REINSERT_NOW')
            source.write_bytes(original)
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            gone.unlink()
            missing.clear()
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
    assert result['status'] == 'PASS', result
    assert result['hold_mid_file'] and result['hold_engaged']
    assert result['hold_result'] == 'HELD_AND_REMOVED'
    assert result['hold_released_by'] in ('card-removed', 'parent-release')
    assert (out / 'PULL_NOW').exists() and (out / 'REINSERT_NOW').exists()
    assert result['part_in_progress_at_interruption']
    assert result['held_file_failed_first'] and result['simulated_by_test']
    assert result['first_failed_error_class'] == 'SOURCE_CHANGED'
    assert 'parts_after_failure' in result
    assert json.loads((out / 'hold-state.json').read_text())['part_size_at_release'] == result['part_size_at_removal']
    assert 0 < result['part_size_at_removal'] < len(original)
    assert result['approvals'] == 1
    captured = json.loads((out / 'after-interruption-files.json').read_text())
    assert not captured['half_final']
    interruption = json.loads((out / 'interruption-state.json').read_text())
    assert interruption['child_exit_code'] != 0
    assert any(asset.get('error') == 'SOURCE_CHANGED' for asset in interruption['assets']), interruption
    plan = json.loads((out / 'plan.json').read_text())['task']['plan']['files']
    readback = json.loads((out / 'final-readback.json').read_text())
    assert {item['rel_path'] for item in readback} == {item['rel_path'] for item in plan}
    assert len(readback) == 3 and all(item['ok'] and item['asset_status'] == 'VERIFIED' for item in readback)
    assert snapshot_tree(folder) == before
    assert json.loads((out / 'source-compare.json').read_text())['identical']
    for path in out.iterdir(): assert_clean(path)
    assert time.monotonic() - started < 40


def test_hold_child_failure_with_card_present_fails_stopped(tmp_path):
    import os

    card, folder, out, args = make_random_hold_run(tmp_path)
    args.pull_timeout = 2
    source = folder / '0.NEF'
    original = source.read_bytes()
    stat = source.stat()
    errors = []

    def simulate():
        try:
            assert wait_for_marker(out / 'PULL_NOW')['held']
            with source.open('r+b') as stream:
                stream.truncate(1024 * 1024)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=simulate)
    worker.start()
    try:
        result = r4.run(args, lambda _: card, base.approve, base.expire_lease)
    finally:
        worker.join(timeout=20)
        source.write_bytes(original)
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert not worker.is_alive()
    assert not errors, errors
    assert result['status'] == 'FAIL_STOPPED', result
    assert result['hold_engaged'] and result['hold_released_by'] == 'timeout'
    assert 'Child failed while card was present' in result['traceback']
    interruption = json.loads((out / 'interruption-state.json').read_text())
    assert interruption['child_exit_code'] != 0
    assert any(asset.get('error') == 'SOURCE_CHANGED' for asset in interruption['assets']), interruption
    assert not (out / 'REINSERT_NOW').exists()
    for path in out.iterdir(): assert_clean(path)


@pytest.mark.parametrize('change', [
    {'hold_result': None},
    {'held_file_failed_first': False},
    {'part_in_progress_at_interruption': False},
    {'child_exit_code': 0},
    {'first_failed_error_class': 'SOURCE_CHANGED'},
])
def test_hold_verdict_rejects_unverified(change):
    evidence = dict(hold_result='HELD_AND_REMOVED', part_in_progress_at_interruption=True,
                    held_file_failed_first=True, child_exit_code=1, first_failed_error_class='ENXIO')
    evidence.update(change)
    verdict, reasons = r4.hold_verdict(evidence)
    assert verdict == 'FAIL_UNVERIFIED_INTERRUPTION' and reasons


def test_hold_verdict_accepts_device_error():
    evidence = dict(hold_result='HELD_AND_REMOVED', part_in_progress_at_interruption=True,
                    held_file_failed_first=True, child_exit_code=1, first_failed_error_class='ENXIO')
    assert r4.hold_verdict(evidence) == ('PASS', [])


def test_failure_evidence_uses_plan_order_and_only_error_class():
    task = {'plan': {'files': [{'asset_id': 'a', 'rel_path': 'a.NEF'},
                               {'asset_id': 'b', 'rel_path': 'b.NEF'}]}}
    interruption = {'child_exit_code': 1, 'assets': [
        {'asset_id': 'b', 'rel_path': 'b.NEF', 'status': 'FAILED', 'error': 'ENOENT /private/path'},
        {'asset_id': 'a', 'rel_path': 'a.NEF', 'status': 'FAILED', 'error': 'ENXIO /private/path'},
    ]}
    evidence = r4.failure_evidence(task, interruption)
    assert evidence['first_failed_file'] == 'a.NEF'
    assert evidence['first_failed_error_class'] == 'ENXIO'
    assert evidence['held_file_failed_first'] and evidence['failed_file_count'] == 2
    assert evidence['later_files_failed_because_card_absent']
    assert '/private/path' not in json.dumps(evidence)
