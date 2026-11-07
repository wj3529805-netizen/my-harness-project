"""Copy standalone NEF, standalone JPEG, and mixed batches.

Fixtures are synthetic labeled bytes, not camera files and not customer pixels.
Ingest-only: these tests do not send files to Lightroom.
"""
from pathlib import Path

import pytest

from cetacea.ingest.pathsafe import read_hash
from conftest import run

MARKER = b'CETACEA-SYNTHETIC-EXAMPLE-NOT-A-CAMERA-FILE\n'

LAYOUTS = {
    'standalone_nef': ['EXAMPLE_ONLY.NEF', 'nested/EXAMPLE_ONLY.nef'],
    'standalone_jpg': ['EXAMPLE_ONLY.JPG', 'EXAMPLE_ONLY.jpeg', 'nested/EXAMPLE_ONLY.jpg'],
    'mixed': [
        'EXAMPLE_PAIR.NEF', 'EXAMPLE_PAIR.JPG',
        'EXAMPLE_NEF_ONLY.NEF', 'EXAMPLE_JPG_ONLY.JPG',
        'nested/EXAMPLE_SAME_STEM.NEF', 'EXAMPLE_JPEG_ONLY.jpeg',
    ],
}


def write_example(path, label):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MARKER + label.encode() + b'\n')


def snapshot(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
        for path in root.rglob('*') if path.is_file()
    }


def kind_for(rel_path):
    return 'raw' if rel_path.lower().endswith('.nef') else 'jpeg'


@pytest.mark.parametrize('layout', list(LAYOUTS))
def test_missing_partner_never_skips_supported_photo(env, layout):
    w, card = env
    names = LAYOUTS[layout]
    for rel in names:
        write_example(card / rel, rel)
    before = snapshot(card)
    scan = w.scan_source('card')
    assert sorted(item['rel_path'] for item in scan['files']) == sorted(names)
    assert scan['skipped'] == []
    assert {item['rel_path']: item['kind'] for item in scan['files']} == {rel: kind_for(rel) for rel in names}

    task = w.plan_import('order', 'p', 'card', stages=['ingest'])
    assert task['plan']['stages'] == ['ingest']
    assert sorted(item['rel_path'] for item in task['plan']['files']) == sorted(names)
    result = run(w, task)
    assert result['state'] == 'COMPLETED', result.get('error')

    assets = w.list_assets(task['task_id'])
    assert sorted(asset['rel_path'] for asset in assets) == sorted(names)
    library = Path(w.config['library_root'])
    for asset in assets:
        assert asset['status'] == 'VERIFIED'
        assert asset['kind'] == kind_for(asset['rel_path'])
        assert not asset['lr_photo_id'] and not asset['lr_status'] and not asset['preset_applied']
        dest = library / asset['dest_rel_path']
        assert read_hash(dest) == asset['sha256'] == read_hash(card / asset['rel_path'])
        assert dest.read_bytes() == (card / asset['rel_path']).read_bytes()
    assert snapshot(card) == before
    assert w.adapter.calls == []
    assert list(Path(w.config['preview_root']).rglob('*')) == []

    inodes = {asset['rel_path']: (library / asset['dest_rel_path']).stat().st_ino for asset in assets}
    assert w.execute(task['task_id'])['state'] == 'COMPLETED'
    assert {asset['rel_path']: (library / asset['dest_rel_path']).stat().st_ino for asset in assets} == inodes
    assert snapshot(card) == before


def test_unpaired_resume_keeps_committed_bytes(env):
    w, card = env
    names = ['EXAMPLE_NEF_ONLY.NEF', 'EXAMPLE_JPG_ONLY.JPG']
    for name in names:
        write_example(card / name, name)
    before = snapshot(card)
    task = w.plan_import('order', 'p', 'card', stages=['ingest'])

    def fault(stage, rel):
        if stage == 'after_commit' and rel == names[0]:
            raise RuntimeError('synthetic interrupt after first commit')

    w.engine.fault_hook = fault
    assert run(w, task)['state'] == 'FAILED'
    library = Path(w.config['library_root'])
    first = next(item for item in task['plan']['files'] if item['rel_path'] == names[0])
    dest = library / first['dest_rel_path']
    assert dest.read_bytes() == (card / names[0]).read_bytes()
    inode, mtime = dest.stat().st_ino, dest.stat().st_mtime_ns

    w.engine.fault_hook = lambda *args: None
    resumed = w.retry(task['task_id'])
    assert resumed['state'] == 'COMPLETED', resumed.get('error')
    assert dest.stat().st_ino == inode and dest.stat().st_mtime_ns == mtime
    assert read_hash(dest) == first['sha256']
    assert sorted(asset['rel_path'] for asset in w.list_assets(task['task_id']) if asset['status'] == 'VERIFIED') == sorted(names)
    assert snapshot(card) == before
    assert w.adapter.calls == []


def test_mixed_conflict_keeps_both_rules(env):
    w, card = env
    write_example(card / 'EXAMPLE_NEF_ONLY.NEF', 'nef')
    write_example(card / 'EXAMPLE_JPG_ONLY.JPG', 'jpg')
    before = snapshot(card)
    task = w.plan_import('order', 'p', 'card', stages=['ingest'])
    jpg = next(item for item in task['plan']['files'] if item['rel_path'] == 'EXAMPLE_JPG_ONLY.JPG')
    dest = Path(w.config['library_root']) / jpg['dest_rel_path']
    dest.parent.mkdir(parents=True)
    different = b'CETACEA-SYNTHETIC-EXAMPLE-DIFFERENT-BYTES\n'
    dest.write_bytes(different)
    inode, mtime = dest.stat().st_ino, dest.stat().st_mtime_ns

    result = run(w, task)
    assert result['state'] == 'FAILED' and 'CONFLICT' in result['error']
    assert dest.read_bytes() == different
    assert dest.stat().st_ino == inode and dest.stat().st_mtime_ns == mtime
    status = {asset['rel_path']: asset['status'] for asset in w.list_assets(task['task_id'])}
    assert status == {'EXAMPLE_JPG_ONLY.JPG': 'CONFLICT', 'EXAMPLE_NEF_ONLY.NEF': 'VERIFIED'}
    assert snapshot(card) == before
    assert w.adapter.calls == []
