"""Bounded device/filesystem acceptance harness; all Lightroom output is MOCK.

Examples (execute only after the named devices are connected):
  .venv/bin/python evidence/mac-acceptance/run_device_filesystem.py --backend local --phase ingest
  .venv/bin/python evidence/mac-acceptance/run_device_filesystem.py --backend apfs --phase probe
  .venv/bin/python evidence/mac-acceptance/run_device_filesystem.py --backend exfat --phase retry

Never enumerates a card: ingest constructs a bounded scan_result for exactly the
one selected file per configured source. Pre/post snapshots and the normal
CopyEngine read that file directly; no card I/O result is simulated.
The harness approves its own isolated test plans with the HUMAN test principal;
it does not add an AI approval tool. No Lightroom process or tool is connected.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from cetacea.core import Workbench
from cetacea import db
from cetacea.ingest.copier import CopyEngine
from cetacea.lightroom import MockLightroomAdapter
from PIL import Image
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']


def below(path, root):
    return Path(os.path.abspath(path)).is_relative_to(Path(os.path.abspath(root)))


def disk_info(path):
    completed = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', str(path)], capture_output=True, timeout=20)
    if completed.returncode:
        raise RuntimeError(f'diskutil info failed for {path}: {completed.stderr.decode(errors="replace")}')
    return plistlib.loads(completed.stdout)


def validate_volume(expected, filesystem=None):
    mount = Path(expected.get('MountPoint') or expected.get('mount') or '')
    expected_uuid = expected.get('VolumeUUID') or expected.get('volume_uuid') or expected.get('volumeUUID')
    if not mount.is_absolute() or not expected_uuid:
        raise ValueError('An absolute mount path and expected VolumeUUID are required')
    info = disk_info(mount)  # Read-only system query before any target creation.
    if not mount.is_dir() or not os.path.ismount(mount):
        raise RuntimeError(f'Mountpoint is absent or is no longer a mount: {mount}')
    if str(info.get('VolumeUUID', '')).lower() != str(expected_uuid).lower():
        raise RuntimeError(f'Volume UUID mismatch at {mount}')
    if Path(info.get('MountPoint', '')) != mount:
        raise RuntimeError(f'diskutil MountPoint mismatch: {info.get("MountPoint")} != {mount}')
    actual_fs = str(info.get('FilesystemType', '')).lower()
    if filesystem and actual_fs != filesystem:
        raise RuntimeError(f'Filesystem mismatch: expected {filesystem}, got {actual_fs}')
    return info


def snapshot_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f'Not a regular file: {path}')
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    result = {'sha256': sha, 'mtime_ns': before.st_mtime_ns, 'size': before.st_size, 'inode': before.st_ino}
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'File changed while reading: {path}')
    return result


def bounded_scan(path, snap):
    """Exact one-file plan; does not call scanner.scan or list the parent."""
    item = {'rel_path': Path(path).name, 'size': snap['size'], 'sha256': snap['sha256'], 'kind': 'raw'}
    digest = hashlib.sha256(json.dumps([(item['rel_path'], item['size'], item['sha256'])], separators=(',', ':')).encode()).hexdigest()
    return {'files': [item], 'skipped': [], 'digest': digest}


class Boundary:
    def __init__(self, mount, target, local, evidence, denied):
        self.mount, self.target = Path(mount), Path(target)
        self.allowed = [self.target, Path(local), Path(evidence)]
        self.denied = [Path(path) for path in denied]
        self.device = self.mount.stat().st_dev

    def alive(self):
        # Recheck immediately before mutations, including each mkdir. This does
        # not create a missing /Volumes mountpoint or any replacement parent.
        if not self.mount.is_dir() or not os.path.ismount(self.mount) or self.mount.stat().st_dev != self.device:
            raise RuntimeError(f'Target volume disappeared or changed: {self.mount}')

    def write(self, path):
        if isinstance(path, int):
            return
        path = Path(os.path.abspath(os.fsdecode(path)))
        if any(below(path, root) for root in self.denied):
            raise PermissionError(f'Card writes are forbidden: {path}')
        if not any(below(path, root) for root in self.allowed):
            raise PermissionError(f'Write outside isolated test roots: {path}')
        self.alive()
        # Refuse an existing symlink anywhere in the target path.
        current = path
        while current != current.parent:
            if current.is_symlink():
                raise PermissionError(f'Symlink in write path: {current}')
            current = current.parent


@contextmanager
def trace_native(boundary, events):
    """Transparent real syscalls; never replace an outcome with unsupported."""
    names = ['link', 'fsync', 'chmod', 'open', 'mkdir', 'rename', 'unlink']
    saved = {name: getattr(os, name) for name in names}
    saved_io_open = io.open
    fd_paths = {}

    def capture(name, fn, args, kwargs, extra=None):
        event = {'operation': name, **(extra or {})}
        try:
            value = fn(*args, **kwargs)
            event['ok'] = True
            return value
        except OSError as exc:
            event.update(ok=False, errno=exc.errno, errno_name=errno.errorcode.get(exc.errno), error=str(exc))
            raise
        finally:
            events.append(event)

    def link(source, destination, *args, **kwargs):
        boundary.write(destination)
        return capture('os.link', saved['link'], (source, destination, *args), kwargs,
                       {'source': str(source), 'destination': str(destination)})
    def chmod(path, mode, *args, **kwargs):
        boundary.write(path)
        before = stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)
        result = capture('os.chmod', saved['chmod'], (path, mode, *args), kwargs,
                         {'path': str(path), 'requested_mode': oct(mode), 'before_mode': oct(before)})
        events[-1]['after_mode'] = oct(stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode))
        return result
    def fsync(fd):
        boundary.alive()
        return capture('os.fsync', saved['fsync'], (fd,), {},
                       {'fd_path': fd_paths.get(fd), 'is_directory': stat.S_ISDIR(os.fstat(fd).st_mode)})
    def open_fd(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            boundary.write(path)
        result = saved['open'](path, flags, *args, **kwargs)
        fd_paths[result] = str(path)
        return result
    def open_io(path, mode='r', *args, **kwargs):
        if any(character in mode for character in 'wax+'):
            boundary.write(path)
        return saved_io_open(path, mode, *args, **kwargs)
    def mkdir(path, *args, **kwargs):
        boundary.write(path)
        return saved['mkdir'](path, *args, **kwargs)
    def rename(source, destination, *args, **kwargs):
        boundary.write(source); boundary.write(destination)
        return saved['rename'](source, destination, *args, **kwargs)
    def unlink(path, *args, **kwargs):
        boundary.write(path)
        return saved['unlink'](path, *args, **kwargs)
    try:
        os.link, os.chmod, os.fsync = link, chmod, fsync
        os.open, io.open, os.mkdir, os.rename, os.unlink = open_fd, open_io, mkdir, rename, unlink
        yield
    finally:
        for name, fn in saved.items():
            setattr(os, name, fn)
        io.open = saved_io_open


def probe(target):
    directory = target / 'capabilities'
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / 'source.bin'
    with source.open('xb') as stream:
        stream.write(b'CETACEA filesystem test only\n'); stream.flush(); os.fsync(stream.fileno())
    observations = {}
    for name, operation in [
        ('hardlink', lambda: os.link(source, directory / 'hardlink.bin')),
        ('chmod', lambda: os.chmod(source, 0o640)),
    ]:
        try:
            operation(); observations[name] = {'ok': True}
        except OSError as exc:
            observations[name] = {'ok': False, 'errno': exc.errno, 'errno_name': errno.errorcode.get(exc.errno), 'error': str(exc)}
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            os.fsync(fd); observations['directory_fsync'] = {'ok': True}
        except OSError as exc:
            observations['directory_fsync'] = {'ok': False, 'errno': exc.errno, 'errno_name': errno.errorcode.get(exc.errno), 'error': str(exc)}
    finally:
        os.close(fd)
    observations['source_readback'] = snapshot_file(source)
    observations['resulting_mode'] = oct(stat.S_IMODE(source.stat().st_mode))
    return observations


def setup_workbench(local, target):
    w = Workbench.init(local / 'home', target / 'library', target / 'preview')
    w.create_order('test', 'Isolated filesystem acceptance test')
    w.add_photographer('tester', 'Acceptance harness')
    w.add_preset('testpreset', 'CETACEA MOCK TEST PRESET')
    assert w.adapter.mock is True
    return w


def approve_and_execute(w, task, report):
    report.setdefault('test_plan_approvals', []).append({'task_id': task['task_id'], 'plan_digest': task['plan_digest'],
        'method': 'Scripted acceptance harness HUMAN API; exact isolated test plan, not an AI MCP approval'})
    w.approve(task['task_id'], task['plan_digest'])
    return w.execute(task['task_id'])


def verify_assets(w, task):
    results = []
    for asset in w.list_assets(task_id=task['task_id']):
        path = Path(w.config['library_root']) / asset['dest_rel_path']
        snap = snapshot_file(path)
        assert asset['status'] == 'VERIFIED' and snap['sha256'] == asset['sha256']
        results.append({'asset_id': asset['asset_id'], 'destination': str(path), 'readback': snap})
    manifests = sorted((Path(w.config['library_root']) / task['plan']['destination'] / '.cetacea').glob('import-manifest-run*.json'))
    assert manifests
    entries = [entry for path in manifests for entry in json.loads(path.read_text())]
    for item in task['plan']['files']:
        assert any(row['asset_id'] == item['asset_id'] and row['sha256'] == item['sha256'] and row['status'] == 'VERIFIED' for row in entries)
    return {'assets': results, 'import_manifests': [str(path) for path in manifests]}


def nooverwrite(w, task, source_parent, local):
    item = task['plan']['files'][0]
    destination = Path(w.config['library_root']) / item['dest_rel_path']
    before = snapshot_file(destination)
    engine = CopyEngine()
    same = engine.copy(source_parent, w.config['library_root'], 'same_' + uuid.uuid4().hex, 0, item)
    assert same['status'] == 'VERIFIED' and same['skipped_verified'] is True, same
    assert snapshot_file(destination) == before
    conflict = local / ('conflict_' + uuid.uuid4().hex)
    conflict.mkdir()
    fake = conflict / item['rel_path']
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_bytes(b'CETACEA isolated different-hash no-overwrite fixture\n')
    changed = {**item, 'sha256': snapshot_file(fake)['sha256'], 'size': fake.stat().st_size}
    different = engine.copy(conflict, w.config['library_root'], 'different_' + uuid.uuid4().hex, 0, changed)
    assert different['status'] == 'CONFLICT' and 'CONFLICT' in different['error'], different
    assert snapshot_file(destination) == before
    return {'same_hash': same, 'different_hash': different, 'destination_unchanged': True, 'destination': before}


def ingest(config, local, target, report):
    w = setup_workbench(local, target)
    output = []
    for selected in config['selected_sources']:
        info = validate_volume(selected['volume'], selected['volume']['FilesystemType'].lower())
        path, parent = Path(selected['path']), Path(selected['parent'])
        assert path.parent == parent and below(path, info['MountPoint'])
        before = snapshot_file(path)
        scan = bounded_scan(path, before)
        w.add_source(selected['source_id'], parent)
        task = w.plan_import('test', 'tester', selected['source_id'], batch_label=selected['source_id'], stages=['ingest'], scan_result=scan)
        completed = approve_and_execute(w, task, report)
        assert completed['state'] == 'COMPLETED', completed
        verification = verify_assets(w, task)
        collisions = nooverwrite(w, task, parent, local)
        validate_volume(selected['volume'], selected['volume']['FilesystemType'].lower())
        after = snapshot_file(path)
        assert before == after, 'Selected card file changed'
        output.append({'source_id': selected['source_id'], 'selected_file': str(path), 'volume': info,
            'scan_scope': 'BOUNDED PRE-SCAN: exactly selected file; no recursive card scanner or directory enumeration',
            'before': before, 'after': after, 'task': completed, 'verification': verification, 'no_overwrite': collisions})
    return output


class FailOnceExport(MockLightroomAdapter):
    def __init__(self):
        super().__init__(); self.failed_asset = None; self.injected = 0
    def _fail(self, stage, file):
        inherited = super()._fail(stage, file)
        if stage == 'export' and file.asset_id == self.failed_asset and not self.injected:
            self.injected += 1
            return True
        return inherited


def pipeline(local, target, report, retry):
    source = local / 'synthetic-source'
    source.mkdir()
    for n in range(4):
        (source / f'MOCK_SYNTHETIC_{n}.NEF').write_bytes((f'CETACEA-MOCK synthetic bytes, not camera RAW {n}\n'.encode()) * 1024)
    (source / 'untouched.xmp').write_bytes(b'CETACEA test sidecar sentinel\n')
    before = {p.name: snapshot_file(p) for p in source.iterdir()}
    w = setup_workbench(local, target)
    adapter = FailOnceExport() if retry else MockLightroomAdapter()
    w.adapter = adapter
    w.add_source('synthetic', source, kind='folder')
    task = w.plan_import('test', 'tester', 'synthetic', batch_label='retry' if retry else 'pipeline', preset_id='testpreset', stages=STAGES)
    if retry:
        adapter.failed_asset = task['plan']['files'][1]['asset_id']
    first = approve_and_execute(w, task, report)
    details = {'fixture_marker': 'MOCK synthetic bytes; no camera RAW decoding or real Lightroom verification', 'initial_task': first}
    if retry:
        assert first['state'] == 'FAILED' and adapter.injected == 1
        with db.connect(w.home) as conn:
            previous = [dict(row) for row in conn.execute('SELECT * FROM previews WHERE task_id=?', (task['task_id'],))]
        assert len(previous) == 3
        old_files = {row['path']: snapshot_file(row['path']) for row in previous}
        successful = {row['asset_id'] for row in previous}
        calls_before = Counter(aid for stage, aid in adapter.calls if stage == 'export')
        completed = w.retry(task['task_id'])
        assert completed['state'] == 'COMPLETED', completed
        calls_after = Counter(aid for stage, aid in adapter.calls if stage == 'export')
        assert all(calls_after[aid] == calls_before[aid] == 1 for aid in successful), (calls_before, calls_after)
        assert calls_after[adapter.failed_asset] == 2 and adapter.injected == 1
        assert all(snapshot_file(path) == snap for path, snap in old_files.items())
        details.update(failure_injections=adapter.injected, failed_asset=adapter.failed_asset,
            export_calls_before=dict(calls_before), export_calls_after=dict(calls_after), old_successful_previews_unchanged=True)
    else:
        completed = first
        assert completed['state'] == 'COMPLETED', completed
    verification = verify_assets(w, task)
    preview = w.verify_preview(task['task_id'])
    assert preview['status'] == 'OK' and preview['mock'] is True and preview['expected_count'] == 4
    for path in Path(w.config['preview_root']).rglob('preview-manifest.json'):
        payload = json.loads(path.read_text())
        assert payload['mock'] is True
        assert all(row['marker'] == 'CETACEA-MOCK' for row in payload['previews'])
    with db.connect(w.home) as conn:
        current_run = conn.execute('SELECT max(run) FROM previews WHERE task_id=?', (task['task_id'],)).fetchone()[0]
        rows = [dict(row) for row in conn.execute('SELECT * FROM previews WHERE task_id=? AND run=?', (task['task_id'], current_run))]
    for row in rows:
        with Image.open(row['path']) as image:
            image.load()
            assert image.format == 'JPEG' and max(image.size) <= 1600 and b'CETACEA-MOCK' in image.info['comment']
        assert snapshot_file(row['path'])['sha256'] == row['sha256']
    collisions = nooverwrite(w, task, source, local)
    after = {p.name: snapshot_file(p) for p in source.iterdir()}
    assert before == after
    assert not list(target.rglob('*.cetacea-lock')) and not list(target.rglob('*.part'))
    details.update(task=completed, verification=verification, preview=preview, no_overwrite=collisions,
        source_before=before, source_after=after, mock_calls=adapter.calls)
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'acceptance-data/device-active.json')
    parser.add_argument('--backend', choices=['local', 'apfs', 'exfat'], required=True)
    parser.add_argument('--phase', choices=['probe', 'ingest', 'pipeline', 'retry'], required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    evidence = Path(config['evidence_root'])
    local_base = Path(config['local_state_root'])
    if not below(evidence, ROOT / 'evidence') or not below(local_base, ROOT / 'acceptance-data'):
        raise ValueError('Evidence and SQLite state must stay in this repository on the Mac')
    evidence.mkdir(parents=True, exist_ok=True)  # Local evidence only; no device writes.
    report = {'backend': args.backend, 'phase': args.phase, 'invocation': run_id,
        'status': 'FAIL', 'marker': 'FILESYSTEM TEST / MOCK LIGHTROOM ONLY', 'native_syscalls': []}
    exit_code = 1
    try:
        if args.backend == 'local':
            info = disk_info(ROOT)
            if str(info.get('FilesystemType', '')).lower() != 'apfs':
                raise RuntimeError('Local target is not APFS')
            info = validate_volume(info, 'apfs')
            mount = Path(info['MountPoint'])
            base = local_base / 'local-target'
            report['target_volume'] = info
        else:
            report['parent_external_volume'] = validate_volume(config['external_volume'], 'apfs')
            if args.backend == 'apfs':
                info = report['parent_external_volume']
                base = Path(config['external_test_root']) / 'apfs'
            else:
                image = config.get('exfat_image', {})
                expected = {**image.get('volume', {}), **image}
                if image.get('mount'):
                    expected['MountPoint'] = image['mount']
                info = validate_volume(expected, 'exfat')
                base = Path(info['MountPoint']) / ('Cetacea-Workbench-Test-' + config['run'])
            mount = Path(info['MountPoint'])
            if not below(base, mount) or base == mount:
                raise ValueError('Target must be a new test descendant of the validated volume')
            report['target_volume'] = info
        target = base / args.phase / run_id
        local = local_base / args.backend / args.phase / run_id
        if below(local, '/Volumes') or below(evidence, '/Volumes'):
            raise ValueError('SQLite/evidence must not be on an external mount')
        boundary = Boundary(mount, target, local, evidence,
            [source['volume']['MountPoint'] for source in config.get('selected_sources', [])])
        report.update(target_root=str(target), local_state=str(local), sqlite_location=str(local / 'home/state.sqlite3'))
        boundary.alive()
        # Create missing test ancestors only after the mounted-volume check.
        # The trace boundary permits ancestors beneath the validated test base,
        # never creating a replacement mountpoint.
        boundary.allowed.append(base)
        if args.backend == 'apfs':
            boundary.allowed.append(Path(config['external_test_root']))
        boundary.allowed.append(local_base)
        with trace_native(boundary, report['native_syscalls']):
            target.mkdir(parents=True, exist_ok=False)
            local.mkdir(parents=True, exist_ok=False)
            if args.phase == 'probe':
                report['observations'] = probe(target)
                report['status'] = 'OBSERVED'  # Unsupported capabilities remain raw evidence, not a blanket pass.
            elif args.phase == 'ingest':
                report['results'] = ingest(config, local, target, report)
                report['status'] = 'PASS'
            else:
                report['results'] = pipeline(local, target, report, retry=args.phase == 'retry')
                report['status'] = 'PASS'
            boundary.alive()
        exit_code = 0
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        path = evidence / f'{args.backend}-{args.phase}-{run_id}.json'
        path.write_text(json.dumps(report, indent=2))
        print(json.dumps({'status': report['status'], 'evidence': str(path), 'error': report.get('error')}, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
