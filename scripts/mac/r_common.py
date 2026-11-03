"""Read-only Mac validation helpers; never write to a source card.

Import from R3/R4 scripts; diskutil resolution is available on macOS only.
"""
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    import cetacea
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from cetacea.appledouble import is_appledouble
from cetacea.ingest.pathsafe import read_hash


def uuid_prefix(value):
    return hashlib.sha256(value.upper().encode()).hexdigest()[:16]


def resolve_mount_by_uuid(uuid, expected_fs=None, diskutil_runner=None):
    if diskutil_runner is None:
        if sys.platform != 'darwin':
            raise RuntimeError('diskutil volume resolution requires macOS')
        diskutil_runner = lambda args: subprocess.check_output(args)
    listing = plistlib.loads(diskutil_runner(['diskutil', 'list', '-plist']))
    candidates = []
    def visit(value):
        if isinstance(value, dict):
            if 'DeviceIdentifier' in value:
                candidates.append(value['DeviceIdentifier'])
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(listing)
    matches = []
    for device in dict.fromkeys(candidates):
        try:
            info = plistlib.loads(diskutil_runner(['diskutil', 'info', '-plist', device]))
        except (subprocess.SubprocessError, OSError, plistlib.InvalidFileException):
            continue
        if (str(info.get('VolumeUUID', '')).upper() == uuid.upper()
                and info.get('MountPoint') and (expected_fs is None or
                str(info.get('FilesystemType', '')).lower() == expected_fs.lower())):
            matches.append(Path(info['MountPoint']))
    if len(matches) != 1:
        raise RuntimeError(f'Expected exactly one mounted volume matching UUID; found {len(matches)}')
    return matches[0]


def volume_guard(uuid, mount, device=None, resolver=resolve_mount_by_uuid):
    current = Path(resolver(uuid)).resolve()
    if current != Path(mount).resolve() or (device is not None and current.stat().st_dev != device):
        raise RuntimeError('Source mount or device changed')
    return current


def desensitize(obj, mapping):
    if isinstance(obj, str):
        for source, replacement in sorted(mapping.items(), key=lambda x: len(str(x[0])), reverse=True):
            obj = obj.replace(str(source), str(replacement))
        return obj
    if isinstance(obj, list): return [desensitize(x, mapping) for x in obj]
    if isinstance(obj, tuple): return [desensitize(x, mapping) for x in obj]
    if isinstance(obj, dict): return {desensitize(k, mapping): desensitize(v, mapping) for k, v in obj.items()}
    return obj


_DIRTY = re.compile(r'/Users/|/Volumes/|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)
def assert_clean(path_or_obj):
    if isinstance(path_or_obj, Path):
        text = path_or_obj.read_text(encoding='utf-8')
    else:
        text = json.dumps(path_or_obj, ensure_ascii=False, default=str)
    if _DIRTY.search(text): raise ValueError('Evidence contains a forbidden path or UUID')


def snapshot_tree(root):
    root = Path(root)
    files, skipped = {}, []
    def walk(directory):
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                path = Path(entry.path); rel = path.relative_to(root).as_posix()
                if entry.is_symlink():
                    skipped.append({'path': rel, 'reason': 'symlink'})
                elif entry.is_dir(follow_symlinks=False): walk(path)
                elif entry.is_file(follow_symlinks=False):
                    if entry.name == '.DS_Store' or is_appledouble(path):
                        skipped.append({'path': rel, 'reason': 'metadata'})
                        continue
                    before = entry.stat(follow_symlinks=False)
                    digest = read_hash(path)
                    after = path.stat(follow_symlinks=False)
                    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                        raise RuntimeError('Source changed during inventory: ' + rel)
                    files[rel] = {'size': after.st_size, 'sha256': digest, 'mtime_ns': after.st_mtime_ns}
                else: skipped.append({'path': rel, 'reason': 'not regular'})
    walk(root)
    return {'files': files, 'skipped': skipped}


def compare_snapshots(before, after):
    a, b = before['files'], after['files']
    added, removed = sorted(b.keys() - a.keys()), sorted(a.keys() - b.keys())
    changed = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    skipped_changed = before['skipped'] != after['skipped']
    return {'identical': not (added or removed or changed or skipped_changed), 'added': added,
            'removed': removed, 'changed': changed, 'skipped_changed': skipped_changed}


@contextmanager
def guard_writes(allowed_root, protected_roots):
    """Reject mutations on protected roots and target-volume paths outside allowed roots.

    Paths using directory descriptors are rejected because their base is ambiguous.
    """
    allowed = [Path(p).resolve() for p in (allowed_root if isinstance(allowed_root, (list, tuple)) else [allowed_root])]
    protected = [Path(p).resolve() for p in protected_roots]
    target_devices = {p.stat().st_dev for p in allowed if p.exists()}
    names = ['open', 'link', 'rename', 'replace', 'mkdir', 'unlink', 'remove', 'chmod', 'truncate']
    originals = {n: getattr(os, n) for n in names}
    def check(path):
        if isinstance(path, int): raise PermissionError('Descriptor mutation is not allowed by write guard')
        p = Path(os.fsdecode(path)).absolute().resolve(strict=False)
        if any(p == r or p.is_relative_to(r) for r in protected): raise PermissionError('Protected source')
        parent = p
        while not parent.exists() and parent != parent.parent: parent = parent.parent
        if parent.stat().st_dev in target_devices and not any(p == r or p.is_relative_to(r) for r in allowed):
            raise PermissionError('Write outside allowed test roots')
    def wrapper(name):
        def call(*args, **kwargs):
            write = name != 'open' or bool(args[1] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if write:
                if any(kwargs.get(k) is not None for k in ('dir_fd', 'src_dir_fd', 'dst_dir_fd')):
                    raise PermissionError('Directory descriptor mutation is not allowed')
                for p in args[:2] if name in ('link', 'rename', 'replace') else args[:1]: check(p)
            return originals[name](*args, **kwargs)
        return call
    try:
        for name in names: setattr(os, name, wrapper(name))
        yield
    finally:
        for name, original in originals.items(): setattr(os, name, original)


def scoped_source(mount, subdir):
    """Resolve a required relative folder without enumerating its ancestors."""
    from cetacea.ingest.pathsafe import relative
    relative(subdir)
    mount = Path(mount).resolve()
    source = (mount / subdir).resolve(strict=True)
    if source == mount or not source.is_relative_to(mount) or not source.is_dir():
        raise ValueError('Source subdirectory must be a folder inside the card')
    return source
