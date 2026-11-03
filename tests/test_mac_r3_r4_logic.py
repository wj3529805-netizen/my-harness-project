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
