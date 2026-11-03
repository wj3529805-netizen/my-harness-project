"""Integrity, subtype, and privacy checks for the owner-provided sample."""
import hashlib
import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'samples' / 'Nikon-Z6III-HE-DSC_9725.NEF'
spec = importlib.util.spec_from_file_location('nef_subtype', ROOT / 'scripts/mac/nef_subtype.py')
nef = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nef)


def open_sample():
    return os.fdopen(os.open(SAMPLE, os.O_RDONLY | os.O_NOFOLLOW), 'rb')


def test_sample_integrity_and_subtype():
    with open_sample() as sample:
        assert os.fstat(sample.fileno()).st_size == 11_537_920
        assert hashlib.file_digest(sample, 'sha256').hexdigest() == (
            'd77f05b50d569de25ce56c435bf7c8d3b40abc250d0a3acee4c376645e941f7e'
        )
    result = nef.classify_file(SAMPLE)
    assert result['subtype'] == 'HE'
    assert result['tag_0x0051_value'] == 13
    assert result['tag_0x0093_value'] is None
    assert result['corroborated'] is True
    assert abs(result['raw_strip_bits_per_pixel'] - 3.0) < 0.001
    assert result['make'] == 'NIKON CORPORATION'
    assert result['model'] == 'NIKON Z6_3'
    assert result['error'] is None


def test_sample_privacy_fields():
    with open_sample() as sample:
        tiff = nef.TIFF(sample, 0, os.fstat(sample.fileno()).st_size)
        entries, _ = tiff.ifd(tiff.first)
        for tag in (0x013b, 0x8298):
            fields = [entry for entry in entries if entry[0] == tag]
            assert len(fields) == 1
            assert fields[0][1] == 2
            assert tiff.data(fields[0]).rstrip(b'\0').decode('ascii') == ''
        gps_fields = [entry for entry in entries if entry[0] == 0x8825]
        assert len(gps_fields) <= 1
        if gps_fields:
            offsets = tiff.integers(gps_fields[0])
            assert len(offsets) == 1 and offsets[0] != 0
            gps_entries, next_ifd = tiff.ifd(offsets[0])
            assert {entry[0] for entry in gps_entries} <= {0x0000}
            assert next_ifd == 0
