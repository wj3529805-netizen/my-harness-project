"""Portable checks of Mac validation safety and evidence helpers."""
import importlib.util
import os
import plistlib
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('r_common', Path(__file__).resolve().parents[1] / 'scripts/mac/r_common.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def test_desensitize_and_clean():
    obj = {'x': ['/Users/jane/foo', '/Volumes/Card/a', '12345678-1234-abCD-1234-123456789012']}
    clean = common.desensitize(obj, {'/Users/jane': '<HOME>', '/Volumes/Card': '<CARD>', obj['x'][2]: '<UUID>'})
    common.assert_clean(clean)
    assert clean['x'][:2] == ['<HOME>/foo', '<CARD>/a']
    with pytest.raises(ValueError): common.assert_clean(obj)


def test_snapshots(tmp_path):
    (tmp_path / 'a').write_bytes(b'a'); (tmp_path / '._a').write_bytes(b'\0\x05\x16\x07x')
    (tmp_path / '.DS_Store').write_bytes(b'x')
    before = common.snapshot_tree(tmp_path)
    assert len(before['skipped']) == 2
    (tmp_path / 'a').write_bytes(b'b'); (tmp_path / 'new').write_bytes(b'x')
    diff = common.compare_snapshots(before, common.snapshot_tree(tmp_path))
    assert diff['changed'] == ['a'] and diff['added'] == ['new']


def test_resolve():
    def runner(args):
        if args[1] == 'list': return plistlib.dumps({'AllDisksAndPartitions': [{'DeviceIdentifier': 'disk1'}]})
        return plistlib.dumps({'VolumeUUID': 'ABC', 'MountPoint': '/test', 'FilesystemType': 'exfat'})
    assert common.resolve_mount_by_uuid('abc', 'exfat', runner) == Path('/test')
    with pytest.raises(RuntimeError): common.resolve_mount_by_uuid('no', diskutil_runner=runner)


@pytest.mark.parametrize('protocol', ['USB', 'Secure Digital'])
def test_volume_info_protocol_and_evidence_privacy(protocol):
    uuid = '12345678-1234-abCD-1234-123456789012'
    mount = '/Volumes/NIKON Z6_3'
    def runner(args):
        if args[1] == 'list':
            return plistlib.dumps({'AllDisksAndPartitions': [{'DeviceIdentifier': 'disk1',
                'Partitions': [{'DeviceIdentifier': 'disk1s1'}]}]})
        if args[-1] == 'disk1':
            return plistlib.dumps({'DeviceIdentifier': 'disk1'})
        return plistlib.dumps({'VolumeUUID': uuid, 'MountPoint': mount,
            'FilesystemType': 'exfat', 'BusProtocol': protocol, 'DeviceIdentifier': 'disk1s1'})
    info = common.volume_info_by_uuid(uuid.lower(), 'EXFAT', runner)
    assert info == {'Protocol': protocol, 'FilesystemType': 'exfat', 'MountPoint': mount}
    assert uuid not in str(info)
    clean = common.desensitize(info, {mount: '<CARD>'})
    common.assert_clean(clean)
    assert clean['MountPoint'] == '<CARD>' and clean['Protocol'] == protocol
    with pytest.raises(ValueError): common.assert_clean(info)


def test_volume_info_missing_protocol_is_not_inferred():
    def runner(args):
        if args[1] == 'list':
            return plistlib.dumps({'disks': [{'DeviceIdentifier': 'disk1s1'}]})
        return plistlib.dumps({'VolumeUUID': 'abc', 'MountPoint': '/test', 'FilesystemType': 'exfat'})
    assert common.volume_info_by_uuid('abc', diskutil_runner=runner)['Protocol'] is None
    with pytest.raises(RuntimeError, match='found 0'):
        common.volume_info_by_uuid('abc', 'apfs', runner)


def test_guard(tmp_path):
    card = tmp_path / 'card'; card.mkdir(); (card / 'input').write_text('safe')
    target = tmp_path / 'target'; target.mkdir()
    original = os.open
    with common.guard_writes(target, [card]):
        assert (card / 'input').read_text() == 'safe'
        fd = os.open(target / 'new', os.O_CREAT | os.O_WRONLY, 0o600); os.close(fd)
        with pytest.raises(PermissionError): os.open(card / 'input', os.O_WRONLY)
        with pytest.raises(PermissionError): os.mkdir(tmp_path / 'outside')
    assert os.open is original


def test_duplicate_uuid_rejected():
    def runner(args):
        if args[1] == 'list':
            return plistlib.dumps({'disks': [{'DeviceIdentifier': 'a'}, {'DeviceIdentifier': 'b'}]})
        return plistlib.dumps({'VolumeUUID': 'abc', 'MountPoint': '/' + args[-1]})
    with pytest.raises(RuntimeError, match='found 2'):
        common.resolve_mount_by_uuid('abc', diskutil_runner=runner)


def test_removed_file(tmp_path):
    p = tmp_path / 'photo'; p.write_bytes(b'photo')
    before = common.snapshot_tree(tmp_path)
    p.unlink()
    assert common.compare_snapshots(before, common.snapshot_tree(tmp_path))['removed'] == ['photo']
