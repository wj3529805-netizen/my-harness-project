"""Guard the tracked text tree against the selected identifiers."""
import importlib.util
import json
from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('r5_desensitize', ROOT / 'scripts/r5_desensitize.py')
r5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r5)


def test_synthetic_redaction():
    home = '/Users/' + 'someone' + '/x'
    other = str(uuid.uuid4())
    text = home + '\n' + json.dumps({'path': home}) + '\n/Users/jane\n' + other
    result, hits = r5.redact_text(text)
    assert result == '<HOME>/x\n' + json.dumps({'path': '<HOME>/x'}) + '\n/Users/jane\n' + other
    assert hits['R-HOME'] == 2


def test_idempotent():
    text = '/Users/' + 'someone' + '/x'
    once, _ = r5.redact_text(text)
    twice, hits = r5.redact_text(once)
    assert twice == once
    assert not any(hits.values())


def test_residuals(monkeypatch):
    assert r5.find_residuals('<HOME>/x <VOLUME_UUID:0123456789abcdef>') == []
    dirty = '/Users/' + 'someone' + '/x'
    assert r5.find_residuals(dirty) == [('R-HOME', 1)]
    volume = '12345678' + '-1234-4234-8234-123456789abc'
    prefix = 'abcdef' + '12'
    full_hash = r5.digest(volume.upper())
    prefix_hash = r5.digest(prefix.upper())
    monkeypatch.setattr(r5, 'FULL_HASHES', {full_hash})
    monkeypatch.setattr(r5, 'PREFIX_HASHES', {prefix_hash: '<VOLUME_UUID_PREFIX>'})
    dirty = volume + '\n' + prefix + '...'
    assert ('R-UUID-FULL', 1) in r5.find_residuals(dirty)
    assert ('R-UUID-PREFIX8', 2) in r5.find_residuals(dirty)
    clean, hits = r5.redact_text(dirty)
    assert clean == '<VOLUME_UUID:' + full_hash[:16] + '>\n<VOLUME_UUID_PREFIX>...'
    assert hits['R-UUID-FULL'] == hits['R-UUID-PREFIX8'] == 1
    assert not r5.find_residuals(clean)


def test_tracked_tree_is_clean():
    failures = []
    for path in r5.iter_files(ROOT):
        for rule, line in r5.find_residuals(path.read_bytes().decode('utf-8')):
            failures.append(f'{path.relative_to(ROOT)}:{line}:{rule}')
    assert not failures, '\n' + '\n'.join(failures)


def test_hash_tables_and_map():
    assert all(re.fullmatch(r'[0-9a-f]{64}', key) for key in r5.FULL_HASHES)
    assert all(re.fullmatch(r'[0-9a-f]{64}', key) for key in r5.PREFIX_HASHES)
    mapping = ROOT / 'evidence/mac-r5/desensitization-map.json'
    if mapping.exists():
        assert json.loads(mapping.read_text(encoding='utf-8'))['baseline_commit']
