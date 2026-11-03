#!/usr/bin/env python3
"""Redact selected identifiers from the current text tree; dry-run by default."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

FULL_HASHES = {
    '39f4499d9fb1c7a3822cd29b6d3b296ca51982d2ab04975fe3f6843e98448fc1',
    '5ae0b1a37395edf7fd7fd18484853f2ecff48bcf27ee40601601b0197861bb0a',
    '0d700d67e691ff250ceefc3ca46c7fa321dd8d0520129fcb0331a70900b88ad7',
    'b9cbb99dcf8d9fa07746f82f558f784c6e1d74a42f78c3a5843237431b48b2b6',
}
PREFIX_HASHES = {
    '0f0517e2dcf92a3828c00ebf2080d0a6e37abe697a0e8dc973c29a433339a67b': '<VOLUME_UUID:39f4499d9fb1c7a3>',
    'ca13af79ed1df88b5c8f1de0dc34df2662705cbfa7ab98594b999276975e8e8f': '<VOLUME_UUID:5ae0b1a37395edf7>',
    'e5589f0434248010996b6d094e49655022d27f481bed55078c338b8281b718ff': '<VOLUME_UUID:0d700d67e691ff25>',
    'de49470d84504c7e053af04f8ea92ac35f768d8a8e0d05bcc8b74e7d757de233': '<VOLUME_UUID:b9cbb99dcf8d9fa0>',
    'b8237f027e0d863ec2cd6d616e895fe3bcf06212ad94de5edb50e6748c3447c9': '<VOLUME_UUID_PREFIX>',
    '7e44fd10214c39e621aedc73f6c0f269192195960e5f951a80d370ee816c8736': '<VOLUME_UUID_PREFIX>',
}
RULES = ('R-HOME', 'R-UUID-FULL', 'R-UUID-PREFIX8')
HOME = re.compile(r'/Users/(?!jane\b|private\b)[A-Za-z0-9._-]+')
UUID = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
PREFIX = re.compile(r'(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}(?![0-9A-Fa-f])')
EXCLUDED = {'scripts/r5_desensitize.py', 'tests/test_privacy_guard.py',
            'evidence/mac-r5/desensitization-map.json'}
START = '<!-- R5-DESENSITIZATION-START -->'
END = '<!-- R5-DESENSITIZATION-END -->'
NOTE = (f'{START}\n'
        '2026-11-03 R5 事后脱敏：主目录路径替换为 `<HOME>`，卷 UUID 替换为 '
        '`<VOLUME_UUID:...>`。原文件哈希和 plan digest 未重新计算。详见 '
        '`evidence/mac-r5/desensitization-map.json` 和 `docs/R5_CLEANUP_PROPOSAL.md`。\n\n'
        'R5 post-hoc redaction on 2026-11-03 replaced home paths with `<HOME>` and volume '
        'UUIDs with `<VOLUME_UUID:...>`. Original file hashes and plan digests were not '
        'recomputed. See `evidence/mac-r5/desensitization-map.json` and '
        '`docs/R5_CLEANUP_PROPOSAL.md`. Scripts in this directory that had literal volume '
        'UUID guards contain placeholders and are no longer runnable as-is; they are retained '
        'as historical records.\n'
        '本目录中原含卷 UUID 字面量检查的脚本因占位符不能直接运行，保留作为历史记录。\n'
        f'{END}\n')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)


def iter_files(root):
    """Yield eligible UTF-8 text paths relative to root's filesystem."""
    root = Path(root).resolve()
    try:
        names = os.fsdecode(_git(root, 'ls-files', '-z')).split('\0')
        paths = (root / name for name in names if name)
    except (subprocess.CalledProcessError, FileNotFoundError):
        def walked():
            for directory, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in {'.git', '.venv', 'third_party-review', 'samples'}]
                yield from (Path(directory) / name for name in files)
        paths = walked()
    for path in sorted(paths):
        rel = path.relative_to(root)
        if (rel.as_posix() in EXCLUDED or 'samples' in rel.parts or
                any(part in {'.git', '.venv', 'third_party-review'} for part in rel.parts) or
                path.suffix.lower() in {'.gz', '.nef'} or path.is_symlink()):
            continue
        try:
            data = path.read_bytes()
            if b'\0' in data:
                continue
            data.decode('utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        yield path


def _redact(text, home_hashes=None):
    hits = Counter({rule: 0 for rule in RULES})
    def full(match):
        key = digest(match.group().upper())
        if key not in FULL_HASHES:
            return match.group()
        hits['R-UUID-FULL'] += 1
        return '<VOLUME_UUID:' + key[:16] + '>'
    def prefix(match):
        replacement = PREFIX_HASHES.get(digest(match.group().upper()))
        if replacement is None:
            return match.group()
        hits['R-UUID-PREFIX8'] += 1
        return replacement
    def home(match):
        hits['R-HOME'] += 1
        if home_hashes is not None:
            home_hashes.add(digest(match.group()[len('/Users/'):]))
        return '<HOME>'
    text = UUID.sub(full, text)
    text = PREFIX.sub(prefix, text)
    text = HOME.sub(home, text)
    return text, dict(hits)


def redact_text(text):
    return _redact(text)


def find_residuals(text):
    results = []
    for rule, regex, accepted in (
        ('R-HOME', HOME, lambda m: True),
        ('R-UUID-FULL', UUID, lambda m: digest(m.group().upper()) in FULL_HASHES),
        ('R-UUID-PREFIX8', PREFIX, lambda m: digest(m.group().upper()) in PREFIX_HASHES),
    ):
        for match in regex.finditer(text):
            if accepted(match):
                results.append((rule, text.count('\n', 0, match.start()) + 1))
    return results


def validate(path, text):
    suffix = path.suffix.lower()
    if suffix == '.json':
        json.loads(text)
    elif suffix == '.jsonl':
        for line in text.splitlines():
            if line.strip():
                json.loads(line)
    elif suffix == '.plist':
        plistlib.loads(text.encode('utf-8'))
    elif suffix == '.py':
        compile(text, str(path), 'exec')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and args.check:
        parser.error('--apply and --check cannot be combined')
    root = args.root.resolve()
    originals = {path.relative_to(root).as_posix(): path.read_bytes().decode('utf-8')
                 for path in iter_files(root)}
    if args.check:
        found = False
        for rel, text in originals.items():
            for rule, line in find_residuals(text):
                print(f'{rule} {rel}:{line}')
                found = True
        return int(found)
    changes = {}
    home_hashes = set()
    totals = Counter({rule: 0 for rule in RULES})
    for rel, old in originals.items():
        new, hits = _redact(old, home_hashes)
        if new != old:
            # XML plist strings require angle brackets to be encoded as entities.
            if Path(rel).suffix.lower() == '.plist':
                new = re.sub(r'<(HOME|VOLUME_UUID(?::[0-9a-f]{16}|_PREFIX))>', r'&lt;\1&gt;', new)
            changes[rel] = [old, new, hits]
            totals.update(hits)
    evidence_dirs = {Path(rel).parts[1] for rel in changes
                     if len(Path(rel).parts) >= 3 and Path(rel).parts[0] == 'evidence'}
    if args.apply:
        for name in sorted(evidence_dirs):
            rel = f'evidence/{name}/README.md'
            path = root / rel
            old = originals.get(rel)
            if old is None:
                old = path.read_bytes().decode('utf-8') if path.exists() else ''
            new = changes.get(rel, [old, old])[1]
            if START not in new and END not in new:
                new += ('\n' if new and not new.endswith('\n') else '') + '\n' + NOTE
            elif (START in new) != (END in new):
                raise ValueError(f'incomplete R5 marker in {rel}')
            if new != old:
                changes[rel] = [old, new, changes.get(rel, [None, None, dict.fromkeys(RULES, 0)])[2]]
    try:
        for rel, (_, new, _) in changes.items():
            validate(root / rel, new)
    except Exception as exc:
        print(f'Validation failed: {rel} ({type(exc).__name__})', file=sys.stderr)
        return 2
    print('Rule totals: ' + ', '.join(f'{rule}={totals[rule]}' for rule in RULES))
    print(f'Files: {len(changes)}')
    for rel, (_, _, hits) in sorted(changes.items(), key=lambda item: (-sum(item[1][2].values()), item[0]))[:10]:
        print(f'  {rel}: {sum(hits.values())}')
    print('Validation: passed')
    if not args.apply or not changes:
        return 0
    def git_info(*command):
        try:
            return _git(root, *command).decode('utf-8').strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return 'unknown'
    entries = []
    for rel, (old, new, hits) in sorted(changes.items()):
        old_bytes, new_bytes = old.encode('utf-8'), new.encode('utf-8')
        old_sha = hashlib.sha256(old_bytes).hexdigest()
        blob = hashlib.sha1(b'blob ' + str(len(old_bytes)).encode() + b'\0' + old_bytes).hexdigest()
        entries.append({'path': rel, 'old_git_blob_sha1': blob, 'old_sha256': old_sha,
                        'new_sha256': hashlib.sha256(new_bytes).hexdigest(), 'hits_by_rule': hits,
                        'embedded_hash_references': sorted(other for other, text in originals.items()
                                                           if other != rel and old_sha in text),
                        'plan_digest_note': bool(re.search(r'\bplan_digests?\b', new))})
    manifest = {'schema_version': 1, 'baseline_commit': git_info('rev-parse', 'HEAD'),
                'baseline_branch': git_info('rev-parse', '--abbrev-ref', 'HEAD'),
                'rules': [
                    {'id': 'R-HOME', 'description': 'Home directory username segment', 'placeholder_pattern': '<HOME>', 'hashed_keys': sorted(home_hashes)},
                    {'id': 'R-UUID-FULL', 'description': 'Selected full volume UUIDs', 'placeholder_pattern': '<VOLUME_UUID:{digest16}>', 'hashed_keys': sorted(FULL_HASHES)},
                    {'id': 'R-UUID-PREFIX8', 'description': 'Selected volume UUID prefixes', 'placeholder_pattern': '<VOLUME_UUID:{digest16}> or <VOLUME_UUID_PREFIX>', 'hashed_keys': sorted(PREFIX_HASHES)},
                ], 'totals': dict(totals), 'files': entries,
                'notes': ['Redaction was post-hoc on the current tree.',
                          'Git history still contains the original values; the public repository history was not rewritten.',
                          'File hashes in this map describe the redacted files and their originals; previously recorded hashes and plan_digests of modified files are not recomputed, so redacted plans cannot re-verify original approvals.',
                          'Harness session/request IDs and the APFS type GUID are retained.']}
    map_path = root / 'evidence/mac-r5/desensitization-map.json'
    map_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    validate(map_path, map_text)
    for rel, (_, new, _) in sorted(changes.items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new.encode('utf-8'))
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(map_text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
