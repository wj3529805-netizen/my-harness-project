"""Synthetic TIFF cases for the read-only Nikon subtype parser."""
import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location('nef_subtype', Path(__file__).resolve().parents[1] / 'scripts/mac/nef_subtype.py')
nef = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nef)


def fixture(value=13, second=None, endian='<'):
    order = b'II' if endian == '<' else b'MM'
    pack = lambda fmt, *v: struct.pack(endian + fmt, *v)
    def entry(tag, typ, count, value): return pack('HHI', tag, typ, count) + value
    maker_entries = []
    if value is not None: maker_entries.append(entry(0x93, 3, 1, pack('H', value) + b'\0\0'))
    if second is not None:
        offset = 8 + 2 + (len(maker_entries) + 1) * 12 + 4
        maker_entries.append(entry(0x51, 7, 12, pack('I', offset)))
    maker = order + pack('HIH', 42, 8, len(maker_entries)) + b''.join(maker_entries) + pack('I', 0)
    if second is not None: maker += b'\0' * 10 + pack('H', second)
    note = b'Nikon\0\x02\x10\0\0' + maker
    make = b'NIKON CORPORATION\0'; model = b'NIKON Z 6_3\0'
    ifd_len = 2 + 3 * 12 + 4
    make_off = 8 + ifd_len; model_off = make_off + len(make)
    exif_off = model_off + len(model); note_off = exif_off + 2 + 12 + 4
    ifd = pack('H', 3) + entry(0x10f, 2, len(make), pack('I', make_off)) + entry(0x110, 2, len(model), pack('I', model_off)) + entry(0x8769, 4, 1, pack('I', exif_off)) + pack('I', 0)
    exif = pack('H', 1) + entry(0x927c, 7, len(note), pack('I', note_off)) + pack('I', 0)
    return order + pack('HI', 42, 8) + ifd + make + model + exif + note


def test_compression_values(tmp_path):
    for i, (value, secondary, expected, endian) in enumerate([(13,None,'HE','<'),(14,None,'HE_STAR','<'),(3,None,'LOSSLESS','<'),(None,14,'HE_STAR','<'),(13,14,'UNKNOWN','<'),(13,None,'HE','>')]):
        p = tmp_path / str(i); p.write_bytes(fixture(value, secondary, endian))
        result = nef.classify_file(p)
        assert result['subtype'] == expected, result
        assert result['make'] == 'NIKON CORPORATION'


def test_malformed_never_raises(tmp_path):
    for i, data in enumerate((b'II', b'II*\0\x08\0\0\0\xff\xff', b'II*\0\x08\0\0\0\0\0\x08\0\0\0')):
        p = tmp_path / str(i); p.write_bytes(data)
        result = nef.classify_file(p)
        assert result['subtype'] == 'UNKNOWN' and result['error']
