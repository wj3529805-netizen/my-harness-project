import os
import sys
from pathlib import Path

import pytest

from cetacea import db
from cetacea.appledouble import is_appledouble, is_ignorable_macos_metadata
from cetacea.ingest.scanner import scan
from cetacea.lightroom import RealLightroomMcpAdapter, VerifiedFile
from conftest import run


MAGIC = b'\x00\x05\x16\x07'


def test_metadata_detection(tmp_path, monkeypatch):
    companion = tmp_path/'._image.jpg'
    companion.write_bytes(MAGIC + b'metadata')
    assert is_appledouble(companion)
    assert is_ignorable_macos_metadata(companion)
    (tmp_path/'image.jpg').write_bytes(MAGIC)
    assert not is_appledouble(tmp_path/'image.jpg')
    companion.write_bytes(b'fake')
    assert not is_appledouble(companion)
    companion.unlink()
    companion.symlink_to(tmp_path/'image.jpg')
    assert not is_appledouble(companion)
    companion.unlink()
    companion.mkdir()
    assert not is_appledouble(companion)
    assert not is_appledouble(tmp_path/'._missing')
    ds = tmp_path/'.DS_Store'
    ds.write_bytes(b'anything')
    assert is_ignorable_macos_metadata(ds)
    ds.unlink()
    ds.symlink_to(tmp_path/'image.jpg')
    assert not is_ignorable_macos_metadata(ds)
    monkeypatch.setattr(os, 'open', lambda *args: (_ for _ in ()).throw(PermissionError()))
    assert not is_appledouble(tmp_path/'._unreadable')


def test_scanner_metadata_and_digest(tmp_path):
    (tmp_path/'X.NEF').write_bytes(b'raw')
    (tmp_path/'X.XMP').write_bytes(b'sidecar')
    baseline = scan(tmp_path)
    for name in ('._X.NEF', '._X.XMP'):
        (tmp_path/name).write_bytes(MAGIC + b'metadata')
    result = scan(tmp_path)
    assert result['files'] == baseline['files']
    assert result['digest'] == baseline['digest']
    assert result['skipped'] == [{'rel_path': name, 'reason': 'appledouble'} for name in ('._X.NEF', '._X.XMP')]
    (tmp_path/'._X.NEF').write_bytes(b'actual raw')
    (tmp_path/'._X.XMP').write_bytes(b'actual sidecar')
    result = scan(tmp_path)
    assert {f['rel_path']: f['kind'] for f in result['files']} == {
        'X.NEF': 'raw', 'X.XMP': 'sidecar', '._X.NEF': 'raw', '._X.XMP': 'sidecar'}
    assert result['digest'] != baseline['digest']


def test_preview_orphans_distinguish_appledouble(env):
    w, card = env
    (card/'X.NEF').write_bytes(b'raw')
    w.add_preset('preset', 'Mock preset')
    task = w.plan_import('order', 'p', 'card', preset_id='preset',
                         stages=['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify'])
    assert run(w, task)['state'] == 'COMPLETED'
    with db.connect(w.home) as c:
        path = Path(c.execute('SELECT path FROM previews WHERE task_id=?', (task['task_id'],)).fetchone()[0])
    companion = path.with_name('._' + path.name)
    companion.write_bytes(MAGIC + b'metadata')
    assert w.verify_preview(task['task_id'])['status'] == 'OK'
    fake = path.parent/'._foo.jpg'
    fake.write_bytes(b'not AppleDouble')
    result = w.verify_preview(task['task_id'])
    assert result['status'] == 'FAILED' and result['orphans'] == [str(fake)]
    assert companion.read_bytes() == MAGIC + b'metadata'


@pytest.mark.parametrize('metadata,success', [(MAGIC + b'metadata', True), (b'fake', False)])
def test_export_selection(tmp_path, metadata, success):
    adapter = RealLightroomMcpAdapter(test_command=[sys.executable])
    raw = tmp_path/'X.NEF'
    raw.write_bytes(b'raw')
    f = VerifiedFile('ast_test', raw, 'unused', 3)
    out = tmp_path/'out'
    out.mkdir()
    def call(name, args):
        directory = Path(args['destination'])
        (directory/'X.jpg').write_bytes(b'jpeg')
        (directory/'._X.jpg').write_bytes(metadata)
        (directory/'.DS_Store').write_bytes(b'system')
        return {'success': True, 'exported': 1, 'complete': True, 'destination': str(directory)}
    adapter.call_tool = call
    result = adapter.export_jpeg([f], out, 1600, 85)[0]
    if success:
        assert result.output_path == out/'ast_test'/'X.jpg' and not result.error
    else:
        assert result.output_path is None and 'expected one regular exported file' in result.error
    assert (out/'ast_test'/'._X.jpg').read_bytes() == metadata


def test_temp_cleanup_preserves_appledouble(planned):
    w, task = planned
    tempdir = Path(w.config['library_root'])/'.cetacea-tmp'/task['task_id']
    tempdir.mkdir(parents=True)
    companion = tempdir/'._0.part'
    companion.write_bytes(MAGIC + b'metadata')
    assert run(w, task)['state'] == 'COMPLETED'
    assert companion.read_bytes() == MAGIC + b'metadata'
