import os
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import PurePosixPath
from .pathsafe import read_hash
from .capture_time import read_capture_time, normalize_filter, local_timezone, matches_capture_time
from ..appledouble import is_appledouble
RAW = set('raf nef nrw arw cr2 cr3 dng orf rw2 pef srw x3f raw 3fr iiq'.split())


def scan(root, capture_filter=None):
    spec = normalize_filter(capture_filter)
    files, skipped = [], []
    # Enumerate first, preserving the legacy traversal order and no-filter shape.
    def walk(path, prefix=''):
        with os.scandir(path) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                rel = prefix + entry.name
                if entry.is_symlink(): skipped.append({'rel_path': rel, 'reason': 'symlink'})
                elif entry.name in {'.DS_Store', 'Thumbs.db'}: skipped.append({'rel_path': rel, 'reason': 'system'})
                elif is_appledouble(entry.path): skipped.append({'rel_path': rel, 'reason': 'appledouble'})
                elif entry.is_dir(follow_symlinks=False): walk(entry.path, rel + '/')
                elif entry.is_file(follow_symlinks=False):
                    ext = entry.name.rsplit('.', 1)[-1].lower()
                    files.append({'rel_path': rel, 'size': entry.stat(follow_symlinks=False).st_size,
                                  'kind': 'raw' if ext in RAW else 'jpeg' if ext in {'jpg', 'jpeg'} else 'sidecar' if ext in {'xmp', 'acr'} else 'other'})
                else: skipped.append({'rel_path': rel, 'reason': 'not regular'})
    walk(root)
    summary = None
    if spec:
        zone = local_timezone(spec['tz'])
        times, photos = {}, {}
        for item in files:
            rel = item['rel_path']
            value = read_capture_time(os.path.join(root, rel), tz=spec['tz'])
            if value is not None:
                times[rel] = (value, 'exif')
                if item['kind'] in {'raw', 'jpeg'}:
                    # Stable traversal priority if RAW and JPEG both have EXIF.
                    photos.setdefault(str(PurePosixPath(rel).with_suffix('')), value)
        matched, excluded, sources = Counter(), Counter(), Counter()
        fallbacks = {'matched': [], 'filtered_out': []}
        fallback_counts = Counter()
        kept, captures = [], []
        for item in files:
            rel = item['rel_path']
            value, source = times.get(rel, (None, None))
            if value is None:
                value = photos.get(str(PurePosixPath(rel).with_suffix('')))
                source = 'companion'
                if value is None:
                    value = datetime.fromtimestamp(os.lstat(os.path.join(root, rel)).st_mtime, zone)
                    source = 'mtime'
            keep = matches_capture_time(value, spec)
            bucket = 'matched' if keep else 'filtered_out'
            # Immediate parent relative to the registered root ('.' for root files).
            folder = str(PurePosixPath(rel).parent)
            (matched if keep else excluded)[folder] += 1
            if source == 'mtime':
                fallback_counts[bucket] += 1
                if sum(map(len, fallbacks.values())) < 50:
                    fallbacks[bucket].append(rel)
            if keep:
                item.update(capture_time=value.isoformat(), capture_time_source=source)
                kept.append(item)
                sources[source] += 1
                captures.append(value)
        summary = {'spec': spec, 'matched': len(kept), 'filtered_out': len(files) - len(kept),
                   'time_source_counts': {key: sources[key] for key in ('exif', 'companion', 'mtime')},
                   'mtime_fallback_matched': fallback_counts['matched'],
                   'mtime_fallback_filtered_out': fallback_counts['filtered_out'],
                   'mtime_fallback_files': fallbacks,
                   'filtered_out_by_folder': dict(sorted(excluded.items())),
                   'matched_by_folder': dict(sorted(matched.items())),
                   'first_capture': min(captures, key=lambda v: v.timestamp()).isoformat() if captures else None,
                   'last_capture': max(captures, key=lambda v: v.timestamp()).isoformat() if captures else None}
        files = kept
    # Filtering precedes all SHA-256 reads. Excluded paths never reach read_hash.
    for item in files:
        item['sha256'] = read_hash(os.path.join(root, item['rel_path']))
        # Retain legacy JSON key order as well as values when no filter is active.
        if spec is None:
            item['kind'] = item.pop('kind')
    digest = hashlib.sha256(json.dumps([(f['rel_path'], f['size'], f['sha256']) for f in files], separators=(',', ':')).encode()).hexdigest()
    result = {'files': files, 'skipped': skipped, 'digest': digest}
    if summary is not None:
        result['capture_filter'] = summary
    return result
