"""User-authorized, bounded real ExFAT acceptance. No formatting or card cleanup.

Only the new TEST_ROOT is writable. Filesystem observers delegate unchanged to
real OS calls; they never manufacture ENOTSUP. The partial-export stimulus uses
the existing explicitly marked MOCK Lightroom adapter. A separate real Lightroom
smoke uses the public RAW and designated test catalog after the R2 checks pass.
"""
import errno
import hashlib
import inspect
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager

from PIL import Image
from cetacea import config, db
from cetacea.appledouble import is_appledouble
from cetacea.core import Workbench
from cetacea.ingest.copier import CopyEngine
from cetacea.ingest.pathsafe import read_hash
from cetacea.lightroom import MockLightroomAdapter

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'evidence/mac-r2-rerun2'
LOCAL = ROOT / 'acceptance-data/mac-r2-rerun2'
UUID = '<VOLUME_UUID:39f4499d9fb1c7a3>'


def resolve_mount():
    matches = []
    for candidate in Path('/Volumes').iterdir():
        if not candidate.is_dir():
            continue
        result = subprocess.run(['diskutil', 'info', '-plist', str(candidate)], capture_output=True)
        if result.returncode != 0:
            continue
        value = plistlib.loads(result.stdout)
        if value.get('VolumeUUID') == UUID and value.get('FilesystemType') == 'exfat':
            matches.append(candidate)
    assert len(matches) == 1, 'Expected exactly one mounted ExFAT volume with the authorized UUID'
    return matches[0]


MOUNT = resolve_mount()
TEST_ROOT = MOUNT / 'Cetacea-R2-Rerun2-20261103'
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']
EVENTS = []
SKIPPED_APPLEDOUBLE = set()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n')


def volume_guard():
    value = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(MOUNT)]))
    assert value['VolumeUUID'] == UUID and value['FilesystemType'] == 'exfat'
    assert value['MountPoint'] == str(MOUNT) and MOUNT.is_mount()
    return value


def snap(path):
    s = path.stat()
    return {'sha256': read_hash(path), 'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'inode': s.st_ino}


def skip_appledouble(path):
    if path.is_relative_to(TEST_ROOT) and is_appledouble(path):
        SKIPPED_APPLEDOUBLE.add(str(path))
        save('appledouble-skipped.json', sorted(SKIPPED_APPLEDOUBLE))
        return True
    return False


def snapshot(path):
    return {str(p.relative_to(path)): snap(p) for p in path.rglob('*') if p.is_file() and not skip_appledouble(p)}


def rows(w, table):
    with db.connect(w.home) as c:
        return [dict(r) for r in c.execute('SELECT * FROM ' + table)]


def check_footprint():
    size = sum(p.stat().st_size for p in TEST_ROOT.rglob('*') if p.is_file())
    assert size < 500_000_000, 'Authorized test footprint exceeded'
    return size


@contextmanager
def observe_real_filesystem():
    originals = {name: getattr(os, name) for name in ['link', 'rename', 'replace', 'mkdir', 'unlink', 'remove', 'chmod', 'open']}
    expected_dev = MOUNT.stat().st_dev

    def check_path(path):
        if isinstance(path, int):
            return False
        p = Path(os.fsdecode(path)).absolute()
        if p.is_relative_to(MOUNT):
            assert MOUNT.is_mount() and MOUNT.stat().st_dev == expected_dev, 'Card detached or changed'
            assert p.is_relative_to(TEST_ROOT) and p.resolve().is_relative_to(TEST_ROOT.resolve()), 'Refuse writing outside new test directory'
            return True
        return False

    def wrap(name):
        original = originals[name]

        def delegated(*args, **kwargs):
            write = name != 'open' or bool(args[1] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            watched = False
            if write:
                for path in args[:2] if name in {'link', 'rename', 'replace'} else args[:1]:
                    watched = check_path(path) or watched
            frame = inspect.currentframe().f_back
            event = {'time': time.time(), 'operation': name,
                     'paths': [os.fsdecode(x) for x in (args[:2] if name in {'link', 'rename', 'replace'} else args[:1]) if not isinstance(x, int)],
                     'caller_file': frame.f_code.co_filename, 'caller_function': frame.f_code.co_name,
                     'caller_line': frame.f_lineno, 'real_os_call': True, 'injected_errno': False}
            try:
                result = original(*args, **kwargs)
                event['success'] = True
                return result
            except OSError as exc:
                event.update(success=False, errno=exc.errno, errno_name=errno.errorcode.get(exc.errno), message=exc.strerror)
                raise
            finally:
                if watched:
                    EVENTS.append(event)
                    with (OUT / 'real-filesystem-events.jsonl').open('a') as f:
                        f.write(json.dumps(event, ensure_ascii=False) + '\n')
        return delegated

    try:
        for name in originals:
            setattr(os, name, wrap(name))
        yield
    finally:
        for name, original in originals.items():
            setattr(os, name, original)


def approve(w, task, name):
    p = subprocess.run([sys.executable, '-m', 'cetacea.cli', '--home', str(w.home), '--json',
                        'approve', task['task_id'], task['plan_digest']], capture_output=True, text=True)
    save(name + '-approval.json', {'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr,
                                 'user_authorization': 'Confirmed R2 isolated SD test directory and scenarios in chat'})
    assert p.returncode == 0, p.stderr


def prepare():
    volume_guard()
    assert not TEST_ROOT.exists() and not LOCAL.exists(), 'Never reuse existing target or local test state'
    save('appledouble-skipped.json', sorted(SKIPPED_APPLEDOUBLE))
    LOCAL.mkdir()
    raw = ROOT / 'acceptance-data/card-cc0/Nikon-Z6.NEF'
    assert read_hash(raw) == '8ca94584578b35a422744c1a610174ce37df0691588edfdecaec3111b3fbbb02'
    with os.fdopen(os.open(raw, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
        public_raw = f.read()
    for name, files in [('source', ['a.NEF', 'b.NEF']), ('source-real', ['public.NEF'])]:
        folder = LOCAL / name
        folder.mkdir()
        for filename in files:
            with (folder / filename).open('xb') as f:
                f.write(public_raw)
    (LOCAL / 'source/existing.XMP').write_bytes(b'R2 synthetic preservation sentinel, not a real editing sidecar.\n')
    (LOCAL / 'conflict-source').mkdir()
    (LOCAL / 'conflict-source/a.NEF').write_bytes(b'R2 synthetic conflict only; this is not a decodable RAW.\n')
    save('source-before.json', snapshot(LOCAL / 'source'))
    save('real-source-before.json', snapshot(LOCAL / 'source-real'))
    save('preexisting-nikon-file-before.json', snap(MOUNT / 'NIKON001.DSC'))
    save('card-write-authorization.json', {'user_confirmed': True, 'volume_uuid': UUID, 'mountpoint': str(MOUNT),
         'new_test_root': str(TEST_ROOT), 'maximum_footprint_bytes': 500_000_000,
         'formatting': False, 'deletion_or_overwrite_of_preexisting_entries': False,
         'authorization_note': 'Second rerun after fdfce5a under the same user authorization; the first rerun (evidence/mac-r2-rerun) failed only in the test script manifest readback on AppleDouble.'})


def filesystem_acceptance():
    volume_guard()
    TEST_ROOT.mkdir()
    w = Workbench.init(LOCAL / 'mock-home', TEST_ROOT / 'mock-library', TEST_ROOT / 'mock-preview')
    w.add_source('public', LOCAL / 'source')
    w.create_order('r2', 'R2 real ExFAT, MOCK Lightroom only')
    w.add_photographer('tester', 'Test operator')
    w.add_preset('mock-preset', 'MOCK R2 preset')
    task = w.plan_import('r2', 'tester', 'public', batch_label='recovery', preset_id='mock-preset', stages=STAGES)
    save('mock-plan.json', task)
    failed_id = next(f['asset_id'] for f in task['plan']['files'] if f['rel_path'] == 'b.NEF')
    assert isinstance(w.adapter, MockLightroomAdapter)
    w.adapter.failures['export'] = {failed_id}
    approve(w, task, 'mock')
    first = w.execute(task['task_id'])
    save('controlled-partial-export.json', first)
    assert first['state'] == 'FAILED' and first['error'] == 'lr_export: 1 failed', first
    previous = rows(w, 'previews')
    assert len(previous) == 1 and previous[0]['mock'] == 1
    old, = previous
    old_snapshot = snap(Path(old['path']))
    save('preview-before-retry.json', {'row': old, 'snapshot': old_snapshot})
    volume_guard()
    w.adapter.failures.clear()
    done = w.retry(task['task_id'])
    save('mock-retry-result.json', done)
    assert done['state'] == 'COMPLETED', done
    verification = w.verify_preview(task['task_id'])
    save('mock-verify-preview.json', verification)
    assert verification['status'] == 'OK' and verification['mock'] is True
    latest = [r for r in rows(w, 'previews') if r['run'] == 2]
    assert len(latest) == 2
    reused, = [r for r in latest if r['asset_id'] == old['asset_id']]
    assert snap(Path(old['path'])) == old_snapshot
    assert read_hash(Path(reused['path'])) == old_snapshot['sha256']
    assert Path(reused['path']).stat().st_ino != Path(old['path']).stat().st_ino
    for a in w.list_assets(task_id=task['task_id']):
        assert read_hash(Path(w.config['library_root']) / a['dest_rel_path']) == a['sha256'] and a['status'] == 'VERIFIED'
    for row in latest:
        with Image.open(row['path']) as im:
            im.load()
            assert im.format == 'JPEG' and b'CETACEA-MOCK' in im.info.get('comment', b'')
        assert read_hash(Path(row['path'])) == row['sha256']
    errors = [e for e in EVENTS if e['operation'] == 'link' and e.get('errno') == errno.ENOTSUP]
    publication = [e for e in errors if e['caller_function'] == 'publish_no_overwrite']
    retry_copy = [e for e in errors if e['caller_function'] == '_lightroom_stage']
    save('real-enotsup-checks.json', {'real_errno_ENOTSUP': errno.ENOTSUP, 'publication_errors': publication,
         'preview_reuse_errors': retry_copy, 'previous_preview_preserved': True, 'reused_preview_new_inode': True,
         'errno_injection': False, 'Lightroom': 'Explicit MOCK stimulus; real ExFAT OS and product fallback'})
    assert publication and retry_copy, 'Required real ENOTSUP paths not both observed: stop, do not simulate'
    before_repeat = {root: snapshot(Path(w.config[root])) for root in ['library_root', 'preview_root']}
    same = w.plan_import('r2', 'tester', 'public', batch_label='recovery', preset_id='mock-preset', stages=STAGES)
    assert same['task_id'] == task['task_id']
    assert w.execute(task['task_id'])['state'] == 'COMPLETED'
    assert before_repeat == {root: snapshot(Path(w.config[root])) for root in before_repeat}
    item = next(f for f in task['plan']['files'] if f['rel_path'] == 'a.NEF')
    target = Path(w.config['library_root']) / item['dest_rel_path']
    target_before = snap(target)
    repeated = CopyEngine().copy(LOCAL / 'source', Path(w.config['library_root']), 'r2-repeat', 0, item)
    assert repeated['status'] == 'VERIFIED' and repeated['skipped_verified'] and snap(target) == target_before
    conflict = dict(item, sha256=read_hash(LOCAL / 'conflict-source/a.NEF'), size=(LOCAL / 'conflict-source/a.NEF').stat().st_size)
    conflicted = CopyEngine().copy(LOCAL / 'conflict-source', Path(w.config['library_root']), 'r2-conflict', 0, conflict)
    save('repeat-and-conflict.json', {'same_task': True, 'repeat_outputs_unchanged': True, 'same_bytes_copy': repeated,
         'different_bytes_copy': conflicted, 'original_test_destination_before': target_before, 'after': snap(target),
         'conflict_scope': 'Only self-created new test directory; original SD entries never conflict targets'})
    assert conflicted['status'] == 'CONFLICT' and snap(target) == target_before
    assert snapshot(LOCAL / 'source') == json.loads((OUT / 'source-before.json').read_text())
    for table in ['tasks', 'task_steps', 'assets', 'previews', 'approvals', 'audit_log']:
        save('mock-' + table + '.json', rows(w, table))
    assert len(rows(w, 'approvals')) == 1
    manifests = []
    for path in TEST_ROOT.rglob('*manifest*.json'):
        if skip_appledouble(path):
            continue
        value = json.loads(path.read_text())
        manifests.append({'path': str(path), 'sha256': read_hash(path), 'content': value})
        for record in value if isinstance(value, list) else value['previews']:
            if 'path' in record:
                assert read_hash(Path(record['path'])) == record['sha256']
            else:
                assert read_hash(Path(w.config['library_root']) / record['dest_rel_path']) == record['sha256']
    save('mock-manifests-readback.json', manifests)
    assert not list(TEST_ROOT.rglob('*.part')) and not list(TEST_ROOT.rglob('*.cetacea-lock'))
    return {'result': 'PASS_REAL_EXFAT_MOCK_LIGHTROOM', 'mock': True, 'task_id': task['task_id'],
            'preview_retry_reused': old['asset_id'], 'real_publication_ENOTSUP': len(publication),
            'real_preview_reuse_ENOTSUP': len(retry_copy), 'footprint_bytes': check_footprint()}


def real_lightroom_smoke():
    volume_guard()
    pids = subprocess.check_output(['pgrep', '-x', 'Adobe Lightroom Classic'], text=True).split()
    assert len(pids) == 1
    fds = subprocess.check_output(['lsof', '-p', pids[0], '-Fn'], text=True)
    catalogs = sorted({s[1:] for s in fds.splitlines() if s.startswith('n') and s.endswith('.lrcat')})
    expected = str(ROOT.parent / 'cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat')
    save('real-catalog-guard.json', {'pid': pids[0], 'open_catalogs': catalogs, 'expected': expected, 'catalog_content_read': False})
    assert catalogs == [expected], 'Stop: not the designated test catalog'
    w = Workbench.init(LOCAL / 'real-home', TEST_ROOT / 'real-library', TEST_ROOT / 'real-preview')
    c = config.load(w.home)
    runtime = ROOT.parent / 'cetacea-workbench/.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js'
    c['lightroom'] = {'adapter': 'real_mcp', 'command': ['/opt/homebrew/bin/node', str(runtime)]}
    c['preview'] = {'max_edge': 1600, 'quality': 85}
    config.save(w.home, c)
    w = Workbench(w.home)
    w.add_source('public', LOCAL / 'source-real')
    w.create_order('real-r2', 'Public RAW only, real Lightroom ExFAT smoke')
    w.add_photographer('tester', 'Test operator')
    w.add_preset('real-preset', 'Cetacea Phase1 Test +0.50')
    t = w.plan_import('real-r2', 'tester', 'public', preset_id='real-preset', stages=STAGES)
    save('real-plan.json', t)
    approve(w, t, 'real')
    result = w.execute(t['task_id'])
    save('real-result.json', result)
    assert result['state'] == 'COMPLETED' and w.adapter.mock is False, result
    verify = w.verify_preview(t['task_id'])
    save('real-verify-preview.json', verify)
    assert verify['status'] == 'OK' and verify['mock'] is False
    a, = w.list_assets(task_id=t['task_id'])
    dest = Path(w.config['library_root']) / a['dest_rel_path']
    assert read_hash(dest) == a['sha256']
    metadata = w.adapter.call_tool('get_photo_metadata', {'photo_ids': [str(dest)], 'sections': ['developSettings']})
    save('real-develop-readback.json', metadata)
    assert metadata['photos'][0]['developSettings']['exposure'] == 0.5
    pv, = rows(w, 'previews')
    with Image.open(pv['path']) as im:
        im.load()
        dimensions = im.size
        assert im.format == 'JPEG' and dimensions == (1600, 1065)
    assert read_hash(Path(pv['path'])) == pv['sha256']
    for table in ['tasks', 'task_steps', 'assets', 'previews', 'approvals', 'audit_log']:
        save('real-' + table + '.json', rows(w, table))
    assert snapshot(LOCAL / 'source-real') == json.loads((OUT / 'real-source-before.json').read_text())
    return {'result': 'PASS_REAL_LIGHTROOM_EXFAT', 'mock': False, 'task_id': t['task_id'],
            'exposure_readback': 0.5, 'dimensions': dimensions, 'raw_sha256': read_hash(dest),
            'preview_sha256': read_hash(Path(pv['path']))}


def main():
    prepare()
    results = {}
    with observe_real_filesystem():
        results['filesystem'] = filesystem_acceptance()
        save('filesystem-result.json', results['filesystem'])
        print('PASS: actual ExFAT ENOTSUP in publication and preview-reuse; repeat/conflict checks passed. Lightroom in this stage is MOCK.', flush=True)
        results['real_lightroom'] = real_lightroom_smoke()
        volume_guard()
        assert snap(MOUNT / 'NIKON001.DSC') == json.loads((OUT / 'preexisting-nikon-file-before.json').read_text())
        save('preexisting-nikon-file-after.json', snap(MOUNT / 'NIKON001.DSC'))
        assert not list(TEST_ROOT.rglob('*.part')) and not list(TEST_ROOT.rglob('*.cetacea-lock'))
        results.update(result='PASS_IN_SCOPE', original_NIKON001_unchanged=True,
                       final_footprint_bytes=check_footprint(), paid_API_calls=0,
                       no_programmatic_write_outside_new_test_root=True,
                       note='OS-maintained .fseventsd/.Trashes are listed, not treated as immutable application photo content; no original card entry is deleted by this script.')
        save('result.json', results)
    print('PASS: R2 real ExFAT plus separate real Lightroom smoke; no paid API.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        save('result.json', {'result': 'FAIL_STOPPED', 'error': repr(exc), 'traceback': traceback.format_exc(),
             'paid_API_calls': 0, 'automatic_retry': False, 'remaining_steps': 'NOT_RUN after failure; preserve created test artifacts'})
        traceback.print_exc()
        sys.exit(1)
