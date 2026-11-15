"""Capture filtering uses only synthetic tmp sources, plus one repository sample."""
import hashlib
import json
import os
import struct
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from cetacea import config
from cetacea.cli import main
from cetacea.core import Workbench, digest
from cetacea.ingest import capture_time, scanner
from cetacea.ingest.capture_time import normalize_filter, read_capture_time

SHANGHAI = ZoneInfo('Asia/Shanghai')
DAY1 = {'date': ['2026-11-14']}
DAY2 = {'date': ['2026-11-15']}


def tiff_bytes(original='2026:11:14 23:59:59', *, order='<', digitized=None,
               modified=None, offset=None, magic=None):
    """Hand-built classic TIFF IFD0 -> ExifIFD with optional ASCII tags."""
    tags = [(tag, value) for tag, value in [(0x9003, original), (0x9004, digitized), (0x9011, offset)] if value is not None]
    root_count = bool(tags) + (modified is not None)
    exif_pos = 8 + 2 + 12 * root_count + 4
    data_pos = exif_pos + (2 + 12 * len(tags) + 4 if tags else 0)
    payload = bytearray()
    def ascii_entry(tag, value):
        raw = value.encode('ascii') + b'\0'
        position = data_pos + len(payload)
        if len(raw) > 4:
            payload.extend(raw)
        return struct.pack(order + 'HHI', tag, 2, len(raw)) + (struct.pack(order + 'I', position) if len(raw) > 4 else raw.ljust(4, b'\0'))
    root = []
    if tags:
        root.append(struct.pack(order + 'HHII', 0x8769, 4, 1, exif_pos))
    if modified is not None:
        root.append(ascii_entry(0x0132, modified))
    exif = [ascii_entry(tag, value) for tag, value in tags]
    header = magic or (b'II*\0' if order == '<' else b'MM\0*')
    def ifd(entries):
        return struct.pack(order + 'H', len(entries)) + b''.join(entries) + b'\0' * 4
    return header + struct.pack(order + 'I', 8) + ifd(root) + (ifd(exif) if tags else b'') + payload


def photo(path, when='2026:11:14 23:59:59', **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = tiff_bytes(when, **kwargs)
    if path.suffix.lower() in {'.jpg', '.jpeg'}:
        payload = b'Exif\0\0' + data
        data = b'\xff\xd8\xff\xe0\x00\x04JF\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload + b'\xff\xd9'
    path.write_bytes(data)
    return path


def mtime_file(path, when):
    path.write_bytes(b'not EXIF')
    stamp = datetime.fromisoformat(when).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def snapshot(root):
    return {str(path.relative_to(root)): (path.lstat().st_size, path.lstat().st_mtime_ns)
            for path in [root, *root.rglob('*')]}


@pytest.mark.parametrize('order', ['<', '>'])
@pytest.mark.parametrize('suffix', ['.NEF', '.jpg'])
def test_tiff_and_jpeg(tmp_path, order, suffix):
    path = photo(tmp_path / ('photo' + suffix), order=order)
    assert read_capture_time(path).isoformat() == '2026-11-14T23:59:59+08:00'


@pytest.mark.parametrize('magic', [b'IIU\0', b'IIRO', b'IIRS'])
def test_raw_header_variants(tmp_path, magic):
    assert read_capture_time(photo(tmp_path/'raw', magic=magic)) is not None


@pytest.mark.parametrize('original,digitized,modified,expected', [
    ('2026:11:14 12:00:00', '2026:11:15 12:00:00', '2026:11:16 12:00:00', 14),
    (None, '2026:11:15 12:00:00', '2026:11:16 12:00:00', 15),
    (None, None, '2026:11:16 12:00:00', 16),
    ('bad', '2026:11:15 12:00:00', '2026:11:16 12:00:00', None),
    (None, 'bad', '2026:11:16 12:00:00', None),
    (None, None, None, None),
])
def test_exif_priority(tmp_path, original, digitized, modified, expected):
    value = read_capture_time(photo(tmp_path/'raw', original, digitized=digitized, modified=modified))
    assert (value.day if value else None) == expected


def test_offset_and_filter_boundary(tmp_path):
    photo(tmp_path/'late.NEF', '2026:11:14 16:00:00', offset='+00:00')
    photo(tmp_path/'early.NEF', '2026:11:14 15:59:59', offset='+00:00')
    assert read_capture_time(tmp_path/'late.NEF').isoformat() == '2026-11-15T00:00:00+08:00'
    assert read_capture_time(tmp_path/'late.NEF', 'UTC').hour == 16
    assert [x['rel_path'] for x in scanner.scan(tmp_path, DAY1)['files']] == ['early.NEF']
    result = scanner.scan(tmp_path, {'from': '2026-11-15', 'to': '2026-11-15T00:00:01'})
    assert [x['rel_path'] for x in result['files']] == ['late.NEF']
    assert result['capture_filter']['first_capture'] == '2026-11-15T00:00:00+08:00'


def test_three_folders_filter_before_hash_and_readonly(env, monkeypatch):
    w, card = env
    for folder in ('143NZ6_3', '144NZ6_3', '145NZ6_3'):
        for day in (14, 15):
            photo(card/'DCIM'/folder/f'day{day}.NEF', f'2026:11:{day} 00:00:00', order='<' if day == 14 else '>')
    before = snapshot(card)
    actual_hash = scanner.read_hash
    hashed = []
    def track(path):
        hashed.append(Path(path).name)
        assert Path(path).name == 'day14.NEF'
        return actual_hash(path)
    monkeypatch.setattr(scanner, 'read_hash', track)
    one = w.plan_import('order', 'p', 'card', capture_filter=DAY1)
    assert hashed == ['day14.NEF'] * 3
    summary = one['plan']['capture_filter']
    assert summary['matched'] == summary['filtered_out'] == 3
    assert summary['time_source_counts'] == {'exif': 3, 'companion': 0, 'mtime': 0}
    assert summary['matched_by_folder'] == summary['filtered_out_by_folder'] == {f'DCIM/{f}': 1 for f in ('143NZ6_3', '144NZ6_3', '145NZ6_3')}
    monkeypatch.setattr(scanner, 'read_hash', actual_hash)
    two = w.plan_import('order', 'p', 'card', capture_filter=DAY2)
    assert one['batch_id'] != two['batch_id']
    assert one['idempotency_key'] != two['idempotency_key']
    assert one['plan_digest'] != two['plan_digest']
    assert not {f['rel_path'] for f in one['plan']['files']} & {f['rel_path'] for f in two['plan']['files']}
    assert not {f['asset_id'] for f in one['plan']['files']} & {f['asset_id'] for f in two['plan']['files']}
    assert w.plan_import('order', 'p', 'card', capture_filter=DAY1)['task_id'] == one['task_id']
    assert snapshot(card) == before


def test_mtime_companions_and_zone(env):
    w, card = env
    photo(card/'a.NEF')
    mtime_file(card/'a.XMP', '2026-11-16T12:00:00+08:00')
    mtime_file(card/'a.acr', '2026-11-16T12:00:00+08:00')
    mtime_file(card/'a.txt', '2026-11-16T12:00:00+08:00')
    mtime_file(card/'fallback.bin', '2026-11-14T16:00:00+00:00')
    mtime_file(card/'corrupt.NEF', '2026-11-14T15:59:59+00:00')
    mtime_file(card/'other.xmp', '2026-11-15T12:00:00+08:00')
    before = snapshot(card)
    result = w.scan_source('card', capture_filter=DAY1)
    summary = result['capture_filter']
    assert summary['matched'] == 5 and summary['filtered_out'] == 2
    assert summary['time_source_counts'] == {'exif': 1, 'companion': 3, 'mtime': 1}
    assert summary['mtime_fallback_matched'] == 1 and summary['mtime_fallback_filtered_out'] == 2
    assert summary['mtime_fallback_files'] == {'matched': ['corrupt.NEF'], 'filtered_out': ['fallback.bin', 'other.xmp']}
    assert {f['capture_time_source'] for f in result['files'] if f['rel_path'].startswith('a.')} == {'exif', 'companion'}
    utc = w.scan_source('card', capture_filter=DAY1, tz='UTC')
    assert utc['capture_filter']['mtime_fallback_matched'] == 2
    assert snapshot(card) == before


def test_companion_is_same_directory_same_stem_only(tmp_path):
    photo(tmp_path/'a.NEF')
    (tmp_path/'sub').mkdir()
    mtime_file(tmp_path/'sub'/'a.xmp', '2026-11-15T12:00:00+08:00')
    mtime_file(tmp_path/'b.xmp', '2026-11-15T12:00:00+08:00')
    result = scanner.scan(tmp_path, DAY1)
    assert len(result['files']) == 1
    assert result['capture_filter']['mtime_fallback_filtered_out'] == 2


def test_fallback_review_list_bounded(tmp_path):
    for i in range(65):
        mtime_file(tmp_path/f'{i:03}.bin', f'2026-11-{14 if i % 2 else 15}T12:00:00+08:00')
    summary = scanner.scan(tmp_path, DAY1)['capture_filter']
    assert summary['mtime_fallback_matched'] == 32
    assert summary['mtime_fallback_filtered_out'] == 33
    assert sum(map(len, summary['mtime_fallback_files'].values())) == 50


@pytest.mark.parametrize('spec', [
    {'date': ['2026-11-14'], 'from': '2026-11-14T23:59:59', 'to': '2026-11-15'},
    {'from': '2026-11-14T15:59:59Z', 'to': '2026-11-14T16:00:00+00:00'},
])
def test_and_range_boundaries(tmp_path, spec):
    for name, stamp in [('before', '2026:11:14 23:59:58'), ('in', '2026:11:14 23:59:59'), ('after', '2026:11:15 00:00:00')]:
        photo(tmp_path/(name+'.NEF'), stamp)
    assert [f['rel_path'] for f in scanner.scan(tmp_path, spec)['files']] == ['in.NEF']


@pytest.mark.parametrize('spec', [
    {'date': ['2026-11-14'], 'from': '2026-11-15'},
    {'date': ['2026-11-16']},
])
def test_no_matches_scan_report_plan_error(env, spec):
    w, card = env
    photo(card/'one.NEF')
    result = w.scan_source('card', capture_filter=spec)
    assert result['capture_filter']['matched'] == 0
    assert result['capture_filter']['first_capture'] is None
    with pytest.raises(ValueError, match='no files match capture filter'):
        w.plan_import('order', 'p', 'card', capture_filter=spec)
    assert w.list_tasks() == []


@pytest.mark.parametrize('spec', [
    {'date': ['2026-02-30']}, {'date': ['20261114']}, {'date': ['2026-1-1']},
    {'date': ['2026-11-14T00:00:00']}, {'date': []}, {'date': '2026-11-14'},
    {'date': [14]}, {'from': '20261114'}, {'from': '2026-11-14X00:00:00'},
    {'to': '2026-11-14T24:00:00'}, {'to': 3}, {'tz': 'Unknown/Zone'},
    {'from': '2026-11-15', 'to': '2026-11-14'},
    {'from': '2026-11-14', 'to': '2026-11-14T00:00:00+08:00'},
    {'from': '2026-11-14T00:00:00Z', 'to': '2026-11-14T01:00:00+08:00'},
    {'dates': ['2026-11-14']}, [], 'invalid',
])
def test_invalid_filter(env, spec):
    w, card = env
    with pytest.raises(ValueError):
        w.plan_import('order', 'p', 'card', capture_filter=spec)
    with pytest.raises(ValueError):
        w.add_source('bad', card, capture_filter=spec)
    assert 'bad' not in w.list_sources()
    assert not w.list_tasks()


def test_normalization_and_equivalent_idempotency(env):
    w, card = env
    photo(card/'one.NEF')
    spec = {'date': ['2026-11-15', '2026-11-14', '2026-11-14'], 'from': '2026-11-14T00:00:00Z'}
    normalized = normalize_filter(spec)
    assert normalized == {'tz': 'Asia/Shanghai', 'date': ['2026-11-14', '2026-11-15'], 'from': '2026-11-14T08:00:00+08:00'}
    one = w.plan_import('order', 'p', 'card', capture_filter=spec)
    assert w.plan_import('order', 'p', 'card', capture_filter=normalized)['task_id'] == one['task_id']
    two = w.plan_import('order', 'p', 'card', capture_filter=DAY1)
    assert one['plan']['files'] == two['plan']['files']
    assert one['idempotency_key'] != two['idempotency_key']
    assert one['plan_digest'] != two['plan_digest']


def test_no_filter_legacy_json_and_digest(env, monkeypatch):
    w, card = env
    (card/'one.NEF').write_bytes(b'legacy fixture')
    def forbidden(*args, **kwargs):
        pytest.fail('no-filter scan must not read EXIF')
    monkeypatch.setattr(scanner, 'read_capture_time', forbidden)
    sha = hashlib.sha256(b'legacy fixture').hexdigest()
    scan_digest = hashlib.sha256(json.dumps([('one.NEF', 14, sha)], separators=(',', ':')).encode()).hexdigest()
    batch = 'b_' + scan_digest[:12]
    base = f'order/p/{batch}'
    asset = 'ast_' + hashlib.sha256('\0'.join(['order', 'p', batch, 'one.NEF', sha]).encode()).hexdigest()[:24]
    expected = {'files': [{'rel_path': 'one.NEF', 'size': 14, 'sha256': sha, 'kind': 'raw', 'dest_rel_path': base+'/one.NEF', 'asset_id': asset}],
                'total_bytes': 14, 'destination': base, 'stages': ['ingest'], 'preset_id': None, 'scan_digest': scan_digest}
    task = w.plan_import('order', 'p', 'card')
    assert task['plan_json'] == json.dumps(expected)
    assert task['plan_digest'] == digest(expected)
    assert task['idempotency_key'] == digest(['order', 'p', 'card', batch, scan_digest, None, ['ingest']])
    assert w.scan_source('card') == {'files': [{'rel_path': 'one.NEF', 'size': 14, 'sha256': sha, 'kind': 'raw'}], 'skipped': [], 'digest': scan_digest}


def test_source_default_and_override(env):
    w, card = env
    photo(card/'one.NEF')
    photo(card/'two.NEF', '2026:11:15 00:00:00')
    w.add_source('default', card, capture_filter=DAY1)
    w = Workbench(w.home)
    assert w.list_sources()['default']['capture_filter'] == normalize_filter(DAY1)
    first = w.plan_import('order', 'p', 'default')
    assert [f['rel_path'] for f in first['plan']['files']] == ['one.NEF']
    second = w.plan_import('order', 'p', 'default', capture_filter=DAY2)
    assert [f['rel_path'] for f in second['plan']['files']] == ['two.NEF']
    assert 'capture_filter' not in w.scan_source('default', capture_filter={})
    unfiltered = w.plan_import('order', 'p', 'default', capture_filter={})
    assert 'capture_filter' not in unfiltered['plan']
    assert len(unfiltered['plan']['files']) == 2
    with pytest.raises(ValueError, match='scan result does not match'):
        w.plan_import('order', 'p', 'default', scan_result=w.scan_source('card'))


def test_config_timezone(env):
    w, card = env
    assert w.config['capture_timezone'] == 'Asia/Shanghai'
    w.config['capture_timezone'] = 'America/New_York'
    config.save(w.home, w.config)
    photo(card/'one.NEF', '2026:11:14 23:59:59')
    mtime_file(card/'mtime', '2026-11-15T04:59:59Z')
    w = Workbench(w.home)
    result = w.scan_source('card', capture_filter=DAY1)
    assert result['capture_filter']['spec']['tz'] == 'America/New_York'
    assert {f['capture_time'] for f in result['files']} == {'2026-11-14T23:59:59-05:00'}


def test_cli_default_repeatable_dates_override_and_range(env, capsys):
    w, card = env
    for folder in ('143NZ6_3', '144NZ6_3', '145NZ6_3'):
        for day in (14, 15):
            photo(card/'DCIM'/folder/f'{day}.NEF', f'2026:11:{day} 00:00:00')
    def cli(*args):
        main(['--home', str(w.home), '--json', *args])
        return json.loads(capsys.readouterr().out)
    cli('source', 'add', 'defaults', str(card), '--date', '2026-11-14', '--tz', 'Asia/Shanghai')
    assert cli('source', 'list')['defaults']['capture_filter'] == normalize_filter(DAY1)
    assert cli('scan', 'defaults')['capture_filter']['matched'] == 3
    assert cli('scan', 'defaults', '--date', '2026-11-15')['capture_filter']['matched'] == 3
    assert cli('scan', 'defaults', '--date', '2026-11-14', '--date', '2026-11-15')['capture_filter']['matched'] == 6
    task = cli('plan', 'order', 'p', 'defaults', '--date', '2026-11-15', '--from', '2026-11-15', '--to', '2026-11-16', '--stages', 'ingest', '--batch-label', 'day2')
    assert task['plan']['capture_filter']['matched'] == 3
    assert task['plan']['capture_filter']['spec']['date'] == ['2026-11-15']
    assert task['batch_id'] == 'day2'
    with pytest.raises(ValueError):
        cli('scan', 'defaults', '--date', '2026-02-30')


def test_parser_corruption_symlink_and_bounds(tmp_path, monkeypatch):
    valid = photo(tmp_path/'good.NEF')
    (tmp_path/'link.NEF').symlink_to(valid)
    assert read_capture_time(tmp_path/'link.NEF') is None
    assert read_capture_time(tmp_path/'absent.NEF') is None
    assert read_capture_time(tmp_path) is None
    for index, content in enumerate([
        b'', b'II*\0', b'II*\0'+struct.pack('<I', 0xffffffff),
        b'II*\0'+struct.pack('<I', 8)+struct.pack('<H', 4097),
        b'II*\0'+struct.pack('<I', 8)+struct.pack('<H', 1)+struct.pack('<HHII', 0x8769, 4, 1, 8)+b'\0'*4,
        b'\xff\xd8\xff\xe1\x00\x01', b'\xff\xd8\xff\xe1\xff\xffExif\0\0',
        b'\xff\xd8\xff\xe1\x00\x08Exif\0\0'+tiff_bytes(),
        tiff_bytes(offset='+24:00'), tiff_bytes(offset='invalid'),
    ]):
        path = tmp_path/f'bad{index}'
        path.write_bytes(content)
        assert read_capture_time(path) is None
    read_sizes = []
    actual_read = capture_time._Reader.read
    def tracked(self, *args, **kwargs):
        data = actual_read(self, *args, **kwargs)
        read_sizes.append(len(data))
        return data
    monkeypatch.setattr(capture_time._Reader, 'read', tracked)
    assert read_capture_time(valid) is not None
    assert sum(read_sizes) <= capture_time.MAX_READ_BYTES
    assert sum(read_sizes) < 1024
    assert read_capture_time(valid, 'Unknown/Zone') is None


def test_repository_sample_nef():
    sample = Path(__file__).resolve().parents[1]/'samples'/'Nikon-Z6III-HE-DSC_9725.NEF'
    if not sample.is_file():
        pytest.skip('repository sample NEF is not present')
    assert isinstance(read_capture_time(sample), datetime)


@pytest.mark.parametrize('offset,expected', [
    ('-05:00', '2026-11-15T01:00:00+08:00'),
    ('+09:00', '2026-11-14T11:00:00+08:00'),
])
def test_positive_and_negative_exif_offsets(tmp_path, offset, expected):
    path = photo(tmp_path/'one.NEF', '2026:11:14 12:00:00', offset=offset)
    assert read_capture_time(path).isoformat() == expected


def test_corrupt_original_uses_mtime_not_digitized(tmp_path):
    path = photo(tmp_path/'one.NEF', 'bad', digitized='2026:11:15 12:00:00')
    stamp = datetime(2026, 11, 14, 12, tzinfo=SHANGHAI).timestamp()
    os.utime(path, (stamp, stamp))
    result = scanner.scan(tmp_path, DAY1)
    assert result['capture_filter']['mtime_fallback_matched'] == 1
    assert result['files'][0]['capture_time_source'] == 'mtime'
    assert result['files'][0]['capture_time'] == '2026-11-14T12:00:00+08:00'


def test_exif_readonly_nofollow_unbuffered(tmp_path, monkeypatch):
    path = photo(tmp_path/'one.NEF')
    actual_open, actual_fdopen = os.open, os.fdopen
    opened, buffering = [], []
    def track_open(path, flags, *args, **kwargs):
        opened.append(flags)
        return actual_open(path, flags, *args, **kwargs)
    def track_fdopen(*args, **kwargs):
        buffering.append(kwargs.get('buffering'))
        return actual_fdopen(*args, **kwargs)
    monkeypatch.setattr(capture_time.os, 'open', track_open)
    monkeypatch.setattr(capture_time.os, 'fdopen', track_fdopen)
    assert read_capture_time(path) is not None
    assert len(opened) == 1
    assert opened[0] & os.O_ACCMODE == os.O_RDONLY
    assert opened[0] & os.O_NOFOLLOW
    assert buffering == [0]
