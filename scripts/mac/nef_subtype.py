"""Read NEF TIFF metadata without modifying the file: python nef_subtype.py FILE...

Uses bounded seeks, O_RDONLY|O_NOFOLLOW, and Nikon NEFCompression values from
https://exiftool.org/TagNames/Nikon.html; absent or conflicting tags are UNKNOWN.
"""
import argparse
import json
import os
import stat
import struct
import subprocess
from pathlib import Path

SOURCE = 'https://exiftool.org/TagNames/Nikon.html (Nikon NEFCompression Values)'
NAMES = {1: ('LOSSY', 'Lossy (type 1)'), 2: ('UNCOMPRESSED', 'Uncompressed'),
         3: ('LOSSLESS', 'Lossless'), 4: ('LOSSY', 'Lossy (type 2)'),
         5: ('OTHER:Striped packed 12 bits', 'Striped packed 12 bits'),
         6: ('OTHER:Uncompressed (reduced to 12 bit)', 'Uncompressed (reduced to 12 bit)'),
         7: ('OTHER:Unpacked 12 bits', 'Unpacked 12 bits'), 8: ('OTHER:Small', 'Small'),
         9: ('OTHER:Packed 12 bits', 'Packed 12 bits'), 10: ('OTHER:Packed 14 bits', 'Packed 14 bits'),
         13: ('HE', 'High Efficiency'), 14: ('HE_STAR', 'High Efficiency* (HE★)')}


class TIFF:
    def __init__(self, f, start, end):
        self.f, self.start, self.end, self.visited = f, start, end, set()
        header = self.read(start, 8)
        if header[:2] not in (b'II', b'MM'): raise ValueError('Invalid TIFF byte order')
        self.endian = '<' if header[:2] == b'II' else '>'
        if self.unpack('H', header[2:4])[0] != 42: raise ValueError('Invalid TIFF magic')
        self.first = self.unpack('I', header[4:8])[0]

    def read(self, pos, count):
        if pos < self.start or count < 0 or pos + count > self.end: raise ValueError('TIFF offset out of bounds')
        self.f.seek(pos); data = self.f.read(count)
        if len(data) != count: raise ValueError('Truncated TIFF')
        return data

    def unpack(self, fmt, data): return struct.unpack(self.endian + fmt, data)

    def ifd(self, offset):
        if offset == 0: return [], 0
        if offset in self.visited: raise ValueError('IFD loop')
        self.visited.add(offset)
        pos = self.start + offset
        count = self.unpack('H', self.read(pos, 2))[0]
        if count > 4096: raise ValueError('IFD entry count exceeds limit')
        raw = self.read(pos + 2, count * 12 + 4)
        entries = []
        for i in range(count):
            entry = raw[i * 12:i * 12 + 12]
            tag, typ, n = self.unpack('HHI', entry[:8])
            entries.append((tag, typ, n, entry[8:12]))
        return entries, self.unpack('I', raw[-4:])[0]

    def data(self, entry, max_bytes=1024 * 1024):
        _, typ, count, field = entry
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}
        if typ not in sizes: raise ValueError('Unsupported TIFF type')
        length = sizes[typ] * count
        if length > max_bytes: raise ValueError('TIFF field exceeds limit')
        return field[:length] if length <= 4 else self.read(self.start + self.unpack('I', field)[0], length)

    def integers(self, entry):
        _, typ, count, _ = entry
        if typ not in (3, 4, 13) or count > 4096: raise ValueError('Invalid integer field')
        return self.unpack(str(count) + ('H' if typ == 3 else 'I'), self.data(entry))


def classify_file(path):
    result = {'subtype': 'UNKNOWN', 'tag_0x0093_value': None, 'tag_0x0051_value': None,
              'tag_0x0093_hex': None, 'make': None, 'model': None, 'method': 'pure-python-tiff-makernote',
              'evidence_source': SOURCE, 'evidence': [], 'error': None,
              'raw_strip_bits_per_pixel': None, 'bpp_subtype': None, 'corroborated': False}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode): raise ValueError('Not a regular file')
            end = info.st_size
            t = TIFF(f, 0, end)
            ifd, next_ifd = t.ifd(t.first)
            exif = None; raw_ifds = []
            for e in ifd:
                if e[0] in (0x10f, 0x110):
                    result['make' if e[0] == 0x10f else 'model'] = t.data(e).rstrip(b'\0').decode('ascii', 'replace')
                elif e[0] == 0x8769: exif = t.integers(e)[0]
                elif e[0] == 0x14a: raw_ifds.extend(t.integers(e))
            if next_ifd: raw_ifds.append(next_ifd)
            while raw_ifds:
                entries, following = t.ifd(raw_ifds.pop())
                if following: raw_ifds.append(following)
                for e in entries:
                    if e[0] == 0x103:
                        result['evidence'].append('Raw IFD Compression 0x0103: ' + ', '.join(map(str, t.integers(e))))
                    elif e[0] == 0x14a: raw_ifds.extend(t.integers(e))
                if result['raw_strip_bits_per_pixel'] is None:
                    fields = {e[0]: e for e in entries if e[0] in (0x100, 0x101, 0x102, 0x103, 0x117)}
                    if all(tag in fields and fields[tag][1] in (3, 4) and fields[tag][2] == 1
                           for tag in (0x100, 0x101, 0x102, 0x103, 0x117)):
                        width, height, bits, compression, strip_bytes = (
                            t.integers(fields[tag])[0] for tag in (0x100, 0x101, 0x102, 0x103, 0x117))
                        if compression == 34713 and width and height and bits and strip_bytes:
                            bpp = round(strip_bytes * 8 / (width * height), 4)
                            result['raw_strip_bits_per_pixel'] = bpp
                            result['evidence'].append(f'Raw strip bits/pixel: {bpp}')
                            if abs(bpp - 3.0) <= 0.05: result['bpp_subtype'] = 'HE'
                            elif abs(bpp - 5.0) <= 0.05: result['bpp_subtype'] = 'HE_STAR'
            if exif:
                entries, _ = t.ifd(exif)
                notes = [e for e in entries if e[0] == 0x927c]
                if notes:
                    note = notes[0]
                    # Check the maker note's declared bounds without loading its bytes.
                    if note[1] not in (1, 7) or note[2] < 18: raise ValueError('Invalid MakerNote field')
                    offset = t.unpack('I', note[3])[0]
                    pos = t.start + offset; length = note[2]
                    header = t.read(pos, 10)
                    if header[:6] != b'Nikon\0' or header[6] != 2:
                        result['evidence'].append('Headerless/type-1 MakerNote: unsupported')
                    else:
                        if pos + length > end: raise ValueError('MakerNote out of bounds')
                        maker = TIFF(f, pos + 10, pos + length)
                        entries, _ = maker.ifd(maker.first)
                        for e in entries:
                            if e[0] == 0x93:
                                try:
                                    if e[1] != 3 or e[2] != 1: raise ValueError('invalid type/count')
                                    value = maker.integers(e)[0]; result['tag_0x0093_value'] = value; result['tag_0x0093_hex'] = hex(value)
                                    result['evidence'].append(f'MakerNote tag 0x0093 int16u: {value}')
                                except ValueError: result['evidence'].append('MakerNote tag 0x0093: unreadable')
                            if e[0] == 0x51:
                                try:
                                    data = maker.data(e)
                                    if e[1] != 7 or len(data) < 12: raise ValueError('invalid type/length')
                                    value = maker.unpack('H', data[10:12])[0]; result['tag_0x0051_value'] = value
                                    result['evidence'].append(f'MakerNote tag 0x0051 byte offset 10 int16u: {value}')
                                except ValueError: result['evidence'].append('MakerNote tag 0x0051: unreadable')
            a, b = result['tag_0x0093_value'], result['tag_0x0051_value']
            if a is not None and b is not None and a != b:
                result['evidence'].append(f'conflict: 0x0093={a}, 0x0051={b}')
            else:
                value = a if a is not None else b
                if value is not None: result['subtype'] = NAMES.get(value, ('UNKNOWN', ''))[0]
            tag_subtype, bpp_subtype = result['subtype'], result['bpp_subtype']
            if tag_subtype in ('HE', 'HE_STAR') and bpp_subtype is not None:
                if tag_subtype == bpp_subtype:
                    result['corroborated'] = True
                    result['evidence'].append('corroborated by raw strip bits/pixel')
                else:
                    result['subtype'] = 'UNKNOWN'
                    result['evidence'].append(f'conflict: tag says {tag_subtype}, strip bits/pixel says {bpp_subtype}')
            elif a is None and b is None and bpp_subtype is not None:
                result['evidence'].append('bits/pixel only: not classifying')
    except (OSError, ValueError, struct.error, OverflowError) as exc:
        result['subtype'] = 'UNKNOWN'; result['error'] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--use-exiftool', action='store_true')
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    output = {}
    for path in args.files:
        item = classify_file(path)
        if args.use_exiftool:
            try:
                p = subprocess.run(['exiftool', '-s3', '-NEFCompression', '-ver', path], capture_output=True, text=True, timeout=30, check=True)
                item['exiftool_crosscheck'] = p.stdout.strip()
                name = NAMES.get(item['tag_0x0093_value'] if item['tag_0x0093_value'] is not None else item['tag_0x0051_value'])
                item['exiftool_disagreement'] = bool(name and name[1].casefold() not in p.stdout.casefold())
            except (OSError, subprocess.SubprocessError) as exc: item['exiftool_crosscheck'] = f'unavailable: {exc}'
        output[str(path)] = item
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == '__main__': main()
