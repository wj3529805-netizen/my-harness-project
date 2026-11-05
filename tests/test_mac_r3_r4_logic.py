"""Exercise scoped runners with synthetic files and no real card."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import pytest

MAC = Path(__file__).resolve().parents[1] / 'scripts/mac'
sys.path.insert(0, str(MAC))
from r_common import assert_clean, scoped_source
import r3_fullcard as r3
import r4_unplug as r4
spec = importlib.util.spec_from_file_location('fixtures_nef', Path(__file__).with_name('test_mac_nef_subtype.py'))
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)


def approve(w, task, timeout, interval):
    worker = threading.Thread(target=w.approve, args=(task['task_id'], task['plan_digest']))
    worker.start()
    try: return r3.wait_approval(w, task, timeout, min(interval, .01))
    finally: worker.join()


def test_scoped_import_and_privacy(tmp_path, monkeypatch):
    card = tmp_path / 'card'; folder = card / 'DCIM' / '142NZ6_3'; folder.mkdir(parents=True)
    (folder / 'one.NEF').write_bytes(fixtures.fixture(13)); (folder / 'two.NEF').write_bytes(fixtures.fixture(14))
    (folder / '._one.NEF').write_bytes(b'\x00\x05\x16\x07' + b'ignored'); (folder / '.DS_Store').write_bytes(b'x')
    sibling = card / 'customer'; sibling.mkdir()
    secret = b'private-decoy-2419' * 137
    for name in ['SECRET_CUSTOMER_001.JPG', 'SECRET_CUSTOMER.RAF', 'SECRET_CUSTOMER.MOV']:
        (sibling / name).write_bytes(secret)
    target = tmp_path / 'target'; target.mkdir(); out = tmp_path / 'evidence'
    real_scandir, real_open = os.scandir, os.open
    def scan(path):
        p = Path(path).absolute()
        assert p != card and not p.is_relative_to(sibling)
        return real_scandir(path)
    def opened(path, flags, *args, **kwargs):
        if not isinstance(path, int): assert not Path(path).absolute().is_relative_to(sibling)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'scandir', scan); monkeypatch.setattr(os, 'open', opened)
    args = r3.parser().parse_args(['--source-uuid','fake','--source-subdir','DCIM/142NZ6_3','--target-base',str(target),'--out',str(out),'--confirm-card-readonly'])
    result = r3.run(args, lambda _: card, approve)
    assert result['status'] == 'PASS', result
    for path in out.iterdir():
        assert_clean(path)
        content = path.read_text()
        assert 'SECRET_CUSTOMER' not in content and f'"size": {len(secret)}' not in content
        assert hashlib.sha256(secret).hexdigest() not in content
    saved = json.loads((out / 'result.json').read_text())
    assert saved['scope'] == 'test-folder-only'
    assert saved['mock'] is False and saved['real_lightroom'] is False
    assert saved['lightroom'] == 'NOT_RUN (ingest-only)'
    assert 'Ingest-only run; no Lightroom stage (neither mock nor real) was executed.' in saved['notes']


@pytest.mark.parametrize('runner', [r3, r4])
def test_failure_result_withholds_unmapped_path(tmp_path, monkeypatch, runner):
    card = tmp_path / 'card'; card.mkdir()
    out = tmp_path / 'out'
    args = runner.parser().parse_args(['--source-uuid', 'fake', '--source-subdir', 'test',
                                       '--out', str(out), '--confirm-card-readonly'])
    def fail(*args):
        raise RuntimeError('failure at /Users/private/unmapped')
    monkeypatch.setattr(runner, 'prepare', fail)
    result = runner.run(args, lambda _: card)
    saved = json.loads((out / 'result.json').read_text())
    assert saved['status'] == 'FAIL_STOPPED'
    assert saved['traceback'] == 'RuntimeError: traceback withheld: contained identifying path'
    assert result['traceback'] == saved['traceback']
    for path in out.iterdir(): assert_clean(path)


def test_reject_unsafe_scope(tmp_path):
    card = tmp_path / 'card'; card.mkdir(); (card / 'escape').symlink_to(tmp_path, target_is_directory=True)
    for name in ('../x', '/tmp', 'escape', ''):
        with pytest.raises((ValueError, FileNotFoundError)): scoped_source(card, name)


def test_missing_subtypes_and_unknown(tmp_path):
    card = tmp_path / 'card'; card.mkdir(); folder = card / 'test'; folder.mkdir()
    (folder / 'x.NEF').write_bytes(fixtures.fixture(99))
    target = tmp_path / 'target'; target.mkdir(); out = tmp_path / 'out'
    args = r3.parser().parse_args(['--source-uuid','fake','--source-subdir','test','--target-base',str(target),'--out',str(out),'--confirm-card-readonly'])
    result = r3.run(args, lambda _: card, approve)
    assert result['status'] == 'PARTIAL_NOT_COVERED', result
    report = json.loads((out / 'subtype-report.json').read_text())
    assert report['raw_values'] == {'99': 1} and report['files']['x.NEF']['tag_0x0093_hex'] == '0x63'
    assert report['files']['x.NEF']['subtype'] == 'UNKNOWN'


def test_kill_recovery(tmp_path):
    card = tmp_path / 'card'; card.mkdir(); folder = card / 'test'; folder.mkdir()
    for i in range(3):
        with (folder / f'{i}.NEF').open('wb') as f: f.truncate(40_000_000)
    target = tmp_path / 'target'; target.mkdir(); out = tmp_path / 'out'
    args = r4.parser().parse_args(['--source-uuid','fake','--source-subdir','test','--target-base',str(target),'--out',str(out),'--confirm-card-readonly','--scenario','kill-process','--poll-interval','0.001','--inter-file-delay','1'])
    def expire(w, task):
        from cetacea import db
        with db.connect(w.home) as c: c.execute('UPDATE tasks SET lease_until=0 WHERE task_id=?', (task['task_id'],))
    result = r4.run(args, lambda _: card, approve, expire)
    assert result['status'] == 'PASS', result
    assert result['final_state'] == 'COMPLETED' and result['approvals'] == 1
    assert result['throttled'] is False and result['throttle_mbps'] is None
    for path in out.iterdir(): assert_clean(path)


def test_interruption_helpers_detect_partial_publication(tmp_path):
    folder = tmp_path / 'card'; folder.mkdir(); (folder / 'a.NEF').write_bytes(b'abcdef')
    w = r3.Workbench.init(tmp_path / 'home', tmp_path / 'library', tmp_path / 'preview')
    task = r3.plan(w, folder)
    dest = Path(w.config['library_root']) / task['plan']['files'][0]['dest_rel_path']
    dest.parent.mkdir(parents=True); dest.write_bytes(b'abc')
    captured = r4.files_state(w, task)
    assert captured['half_final'] and not captured['published'][0]['ok']
    class Done:
        def poll(self): return 0
    assert not r4.observe_copy(Done(), w, task, 0)


def test_throttled_reader_rate_and_integrity():
    import io
    import time
    data = b'abcde' * 100_000
    start = time.monotonic()
    with r4.ThrottledReader(io.BytesIO(data), 5) as stream:
        assert stream.read() == data
    assert .09 <= time.monotonic() - start < 1


def test_watched_directory_matches_copy_engine(tmp_path):
    from cetacea.ingest.copier import CopyEngine
    source = tmp_path / 'source'; source.mkdir()
    (source / 'a.NEF').write_bytes(b'abc')
    library = tmp_path / 'library'; library.mkdir()
    task_id = 'test-task'
    item = {'rel_path': 'a.NEF', 'dest_rel_path': 'a.NEF', 'sha256': hashlib.sha256(b'abc').hexdigest()}
    seen = []
    def hook(stage, rel):
        if stage == 'after_temp_write':
            seen.extend(library.rglob('*.part'))
    assert CopyEngine(hook).copy(source, library, task_id, 7, item)['status'] == 'VERIFIED'
    assert seen == [library / '.cetacea-tmp' / task_id / '7.part']


def expire_lease(w, task):
    from cetacea import db
    with db.connect(w.home) as c: c.execute('UPDATE tasks SET lease_until=0 WHERE task_id=?', (task['task_id'],))


def make_throttled_run(tmp_path, scenario):
    card = tmp_path / 'card'; folder = card / 'test'; folder.mkdir(parents=True)
    for i in range(3):
        (folder / f'{i}.NEF').write_bytes(bytes([i + 1]) * 6_000_000)
    target = tmp_path / 'target'; target.mkdir(); out = tmp_path / 'out'
    args = r4.parser().parse_args(['--source-uuid', 'fake', '--source-subdir', 'test', '--target-base', str(target), '--out', str(out), '--confirm-card-readonly', '--scenario', scenario, '--throttle-mbps', '8', '--pull-timeout', '10', '--reinsert-timeout', '10'])
    return card, folder, out, args


def test_throttled_kill_observes_real_growth(tmp_path):
    card, folder, out, args = make_throttled_run(tmp_path, 'kill-process')
    result = r4.run(args, lambda _: card, approve, expire_lease)
    assert result['status'] == 'PASS', result
    assert result['throttled'] and result['throttle_mbps'] == 8
    assert result['part_in_progress_at_interruption'] and result['approvals'] == 1
    captured = json.loads((out / 'after-interruption-files.json').read_text())
    assert not captured['half_final'] and captured['parts'][0]['size'] >= 1024 * 1024
    plan = json.loads((out / 'plan.json').read_text())
    assert plan['watched_temp_dir_rel'] == '.cetacea-tmp/' + plan['task']['task_id']
    assert not (out / 'PULL_NOW').exists()
    for path in out.iterdir(): assert_clean(path)


def test_unplug_markers_with_simulated_removal(tmp_path, monkeypatch):
    import time
    card, folder, out, args = make_throttled_run(tmp_path, 'unplug')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    missing = threading.Event()
    child = []
    original = r4.subprocess.Popen
    def launch(*a, **kw):
        proc = original(*a, **kw); child.append(proc); return proc
    monkeypatch.setattr(r4.subprocess, 'Popen', launch)
    def resolver(_):
        if missing.is_set(): raise RuntimeError('simulated removal')
        return card
    def simulate():
        deadline = time.monotonic() + 15
        while not (out / 'PULL_NOW').exists() and time.monotonic() < deadline: time.sleep(.01)
        if not (out / 'PULL_NOW').exists(): return
        missing.set()
        # Simulate the read failure without mutating the read-only source tree.
        child[0].kill()
        while not (out / 'REINSERT_NOW').exists() and time.monotonic() < deadline: time.sleep(.01)
        missing.clear()
    worker = threading.Thread(target=simulate); worker.start()
    try: result = r4.run(args, resolver, approve, expire_lease)
    finally: worker.join(timeout=16)
    assert result['status'] == 'PASS', result
    assert (out / 'PULL_NOW').exists() and (out / 'REINSERT_NOW').exists()
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    for path in out.iterdir(): assert_clean(path)


def test_r4_default_throttle_off():
    args = r4.parser().parse_args(['--source-uuid', 'fake', '--source-subdir', 'test', '--confirm-card-readonly'])
    assert args.throttle_mbps is None and args.inter_file_delay == 0 and args.poll_interval == .05


def test_throttled_copy_exposes_multiple_chunk_sizes(tmp_path, monkeypatch):
    import time
    import cetacea.ingest.copier as copier
    source = tmp_path / 'source'; source.mkdir()
    data = b'x' * 4_000_000
    (source / 'a.NEF').write_bytes(data)
    library = tmp_path / 'library'; library.mkdir()
    item = {'rel_path': 'a.NEF', 'dest_rel_path': 'a.NEF', 'sha256': hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(copier, 'os', r4.CopierOSProxy(8))
    result = []
    worker = threading.Thread(target=lambda: result.append(copier.CopyEngine().copy(source, library, 'task', 0, item)))
    worker.start()
    sizes = set()
    part = library / '.cetacea-tmp' / 'task' / '0.part'
    while worker.is_alive():
        try: sizes.add(part.stat().st_size)
        except FileNotFoundError: pass
        time.sleep(.01)
    worker.join()
    assert result[0]['status'] == 'VERIFIED'
    assert 1024 * 1024 in sizes and 2 * 1024 * 1024 in sizes


def test_r4_reinsert_changed_device_and_deleted_part(tmp_path, monkeypatch):
    import time
    card, folder, out, args = make_throttled_run(tmp_path, 'unplug')
    args.poll_interval = .005
    missing = threading.Event()
    child = []
    original_launch = r4.subprocess.Popen
    original_prepare = r4.prepare
    original_state = r4.files_state
    def prepare(*a):
        mount, device, source, target, home, mapping = original_prepare(*a)
        return mount, device + 1, source, target, home, mapping
    def guard(args, resolver, mount, device):
        from r_common import volume_guard
        assert device == (None if (out / 'REINSERT_NOW').exists() else mount.stat().st_dev + 1)
        volume_guard(args.source_uuid, mount, None, resolver)
    def launch(*a, **kw):
        proc = original_launch(*a, **kw); child.append(proc); return proc
    def files_state(w, task):
        state = original_state(w, task)
        if missing.is_set(): state['parts'] = []
        return state
    monkeypatch.setattr(r4, 'prepare', prepare)
    monkeypatch.setattr(r4, 'guard', guard)
    monkeypatch.setattr(r4.subprocess, 'Popen', launch)
    monkeypatch.setattr(r4, 'files_state', files_state)
    def resolver(_):
        if missing.is_set(): raise RuntimeError('removed')
        return card
    def simulate():
        deadline = time.monotonic() + 15
        while not (out / 'PULL_NOW').exists() and time.monotonic() < deadline: time.sleep(.005)
        time.sleep(.1)
        missing.set(); child[0].kill()
        while not (out / 'REINSERT_NOW').exists() and time.monotonic() < deadline: time.sleep(.005)
        missing.clear()
    worker = threading.Thread(target=simulate); worker.start()
    try: result = r4.run(args, resolver, approve, expire_lease)
    finally: worker.join(timeout=16)
    assert result['status'] == 'PASS', result
    assert result['source_st_dev_changed'] is True
    assert result['source_st_dev_before'] != result['source_st_dev_after_reinsert']
    assert result['part_in_progress_at_interruption']
    assert result['part_evidence_source'] == 'last_seen_before_removal'
    assert result['part_sizes_at_pull_detection'] == []
    assert json.loads((out / 'result.json').read_text())['source_st_dev_changed'] is True


@pytest.mark.parametrize('mismatch', ['uuid', 'path'])
def test_r4_reinsert_rejects_wrong_identity(tmp_path, mismatch):
    import time
    card, folder, out, args = make_throttled_run(tmp_path, 'unplug')
    args.reinsert_timeout = .3; args.poll_interval = .005
    other = tmp_path / 'other'; other.mkdir()
    removed = threading.Event()
    def resolver(uuid):
        assert uuid == 'fake'
        if removed.is_set():
            if mismatch == 'uuid': raise RuntimeError('UUID not found')
            return other
        return card
    def simulate():
        deadline = time.monotonic() + 15
        while not (out / 'PULL_NOW').exists() and time.monotonic() < deadline: time.sleep(.005)
        removed.set()
    worker = threading.Thread(target=simulate); worker.start()
    try: result = r4.run(args, resolver, approve, expire_lease)
    finally: worker.join(timeout=16)
    assert result['status'] == 'FAIL_STOPPED'
    assert 'Same card must return at the original mountpoint' in result['traceback']


def test_r4_unplug_without_partial_is_not_pass(tmp_path, monkeypatch):
    import time
    card, folder, out, args = make_throttled_run(tmp_path, 'unplug')
    args.poll_interval = .005
    missing = threading.Event(); child = []
    original_launch = r4.subprocess.Popen
    original_state = r4.files_state
    def launch(*a, **kw):
        proc = original_launch(*a, **kw); child.append(proc); return proc
    def files_state(w, task):
        value = original_state(w, task)
        if (out / 'PULL_NOW').exists(): value['parts'] = []
        return value
    monkeypatch.setattr(r4.subprocess, 'Popen', launch)
    monkeypatch.setattr(r4, 'files_state', files_state)
    def resolver(_):
        if missing.is_set(): raise RuntimeError('removed')
        return card
    def simulate():
        deadline = time.monotonic() + 15
        while not (out / 'PULL_NOW').exists() and time.monotonic() < deadline: time.sleep(.005)
        time.sleep(.1); missing.set(); child[0].kill()
        while not (out / 'REINSERT_NOW').exists() and time.monotonic() < deadline: time.sleep(.005)
        missing.clear()
    worker = threading.Thread(target=simulate); worker.start()
    try: result = r4.run(args, resolver, approve, expire_lease)
    finally: worker.join(timeout=16)
    assert result['status'] == 'FAIL_UNVERIFIED_INTERRUPTION', result
    assert not result['part_in_progress_at_interruption']
