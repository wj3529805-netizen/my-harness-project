"""Bounded, read-only EXIF times and local capture-filter normalization.

Priority is ExifIFD DateTimeOriginal (0x9003), then DateTimeDigitized
(0x9004) only when Original is absent, then IFD0 DateTime (0x0132) only
when both are absent. An invalid higher-priority value never falls through.
No MakerNotes, image pixels, external tools, or source writes are needed.
"""
import os
import re
import stat
import struct
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = 'Asia/Shanghai'
MAX_READ_BYTES = 1024 * 1024
MAX_IFD_ENTRIES = 4096
_DATE = r'\d{4}-\d{2}-\d{2}'
_ISO = re.compile(_DATE + r'(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?\Z', re.ASCII)


def local_timezone(tz=None):
    try:
        return ZoneInfo(DEFAULT_TIMEZONE if tz is None else tz)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError('invalid capture timezone') from exc


def normalize_filter(spec=None, tz=None):
    """Return one JSON-safe spec, or None for no date/range constraint."""
    if spec is None:
        spec = {}
    if not isinstance(spec, dict) or set(spec) - {'date', 'from', 'to', 'tz'}:
        raise ValueError('invalid capture filter')
    zone = local_timezone(tz if tz is not None else spec.get('tz'))
    result = {'tz': zone.key}
    dates = spec.get('date')
    if dates is not None:
        if not isinstance(dates, list) or not dates:
            raise ValueError('date must be a nonempty list of YYYY-MM-DD dates')
        for value in dates:
            if not isinstance(value, str) or not re.fullmatch(_DATE, value, re.ASCII):
                raise ValueError('date must use YYYY-MM-DD')
            date.fromisoformat(value)
        result['date'] = sorted(set(dates))
    limits = {}
    for key in ('from', 'to'):
        value = spec.get(key)
        if value is not None:
            if not isinstance(value, str) or not _ISO.fullmatch(value):
                raise ValueError(f'{key} must be an ISO datetime or YYYY-MM-DD')
            parsed = datetime.fromisoformat(value)
            parsed = parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
            limits[key] = parsed.timestamp()
            result[key] = parsed.isoformat()
    if 'from' in limits and 'to' in limits and limits['from'] >= limits['to']:
        raise ValueError('capture filter from must be earlier than to')
    return result if len(result) > 1 else None


def matches_capture_time(value, spec):
    zone = local_timezone(spec['tz'])
    value = value.astimezone(zone)
    if 'date' in spec and value.date().isoformat() not in spec['date']:
        return False
    stamp = value.timestamp()
    return (('from' not in spec or stamp >= datetime.fromisoformat(spec['from']).timestamp())
            and ('to' not in spec or stamp < datetime.fromisoformat(spec['to']).timestamp()))


class _Reader:
    def __init__(self, stream):
        self.stream = stream
        self.size = os.fstat(stream.fileno()).st_size
        self.remaining = MAX_READ_BYTES

    def read(self, offset, size, start=0, end=None):
        end = self.size if end is None else end
        if offset < start or size < 0 or size > self.remaining or offset + size > end:
            raise ValueError('EXIF read bound exceeded')
        self.remaining -= size
        self.stream.seek(offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError('truncated EXIF')
        return data

    def tiff(self, base, end):
        def read(offset, size):
            return self.read(base + offset, size, base, end)
        header = read(0, 8)
        if header[:4] not in (b'II*\0', b'MM\0*', b'IIU\0', b'IIRO', b'IIRS'):
            raise ValueError('unsupported TIFF header')
        order = '<' if header[:2] == b'II' else '>'
        visited = set()

        def ifd(offset):
            if offset < 8 or offset in visited:
                raise ValueError('invalid or cyclic IFD')
            visited.add(offset)
            count = struct.unpack(order + 'H', read(offset, 2))[0]
            if count > MAX_IFD_ENTRIES:
                raise ValueError('too many IFD entries')
            data = read(offset + 2, count * 12 + 4)
            entries = {}
            for pos in range(0, count * 12, 12):
                tag, kind, length = struct.unpack(order + 'HHI', data[pos:pos + 8])
                if tag in {0x8769, 0x9003, 0x9004, 0x0132, 0x9011}:
                    if tag in entries:
                        raise ValueError('duplicate EXIF tag')
                    entries[tag] = kind, length, data[pos + 8:pos + 12]
            return entries

        def ascii_value(entry):
            kind, length, raw = entry
            if kind != 2 or not 1 <= length <= 256:
                raise ValueError('invalid EXIF ASCII')
            data = raw[:length] if length <= 4 else read(struct.unpack(order + 'I', raw)[0], length)
            return data.rstrip(b'\0').decode('ascii')

        root = ifd(struct.unpack(order + 'I', header[4:8])[0])
        exif = {}
        if 0x8769 in root:
            kind, length, raw = root[0x8769]
            if kind not in {4, 13} or length != 1:
                raise ValueError('invalid ExifIFD pointer')
            exif = ifd(struct.unpack(order + 'I', raw)[0])
        selected = next((exif[tag] for tag in (0x9003, 0x9004) if tag in exif), root.get(0x0132))
        if selected is None:
            return None
        text = ascii_value(selected)
        if not re.fullmatch(r'\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}', text, re.ASCII):
            raise ValueError('invalid EXIF datetime')
        value = datetime.strptime(text, '%Y:%m:%d %H:%M:%S')
        if 0x9011 in exif:
            offset = ascii_value(exif[0x9011])
            if not re.fullmatch(r'[+-]\d{2}:\d{2}', offset, re.ASCII):
                raise ValueError('invalid EXIF timezone offset')
            hours, minutes = int(offset[1:3]), int(offset[4:6])
            if hours > 23 or minutes > 59:
                raise ValueError('invalid EXIF timezone offset')
            delta = timedelta(hours=hours, minutes=minutes)
            value = value.replace(tzinfo=timezone(delta if offset[0] == '+' else -delta))
        return value

    def capture(self):
        if self.read(0, 2) != b'\xff\xd8':
            return self.tiff(0, self.size)
        offset = 2
        for _ in range(512):
            marker = self.read(offset, 2)
            offset += 2
            if marker[0] != 0xff:
                raise ValueError('invalid JPEG marker')
            while marker[1] == 0xff:
                marker = b'\xff' + self.read(offset, 1)
                offset += 1
            code = marker[1]
            if code in {0xda, 0xd9}:
                return None
            if code == 0x01 or 0xd0 <= code <= 0xd7:
                continue
            length = struct.unpack('>H', self.read(offset, 2))[0]
            if length < 2 or offset + length > self.size:
                raise ValueError('invalid JPEG segment')
            if code == 0xe1 and length >= 8 and self.read(offset + 2, 6) == b'Exif\0\0':
                return self.tiff(offset + 8, offset + length)
            offset += length
        raise ValueError('too many JPEG segments')


def read_capture_time(path, tz=None) -> datetime | None:
    """Return a timezone-aware capture time, or None on any read/parse error.

    At most 1 MiB is read using bounded seeks and at most two noncyclic IFDs.
    Naive camera times are local in tz (default Asia/Shanghai); OffsetTimeOriginal
    is converted to that zone. Only regular files are parsed; opens are
    read-only/no-follow, unbuffered so read-ahead cannot exceed the byte budget.
    """
    try:
        zone = local_timezone(tz)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb', buffering=0) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            value = _Reader(stream).capture()
        if value is None:
            return None
        return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)
    except Exception:
        return None
