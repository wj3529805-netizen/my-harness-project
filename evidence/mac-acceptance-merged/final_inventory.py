"""Read-only final checks: fixture sidecars, unique imports, approval reuse."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time
import traceback

from run_acceptance import DATA, OUT, hash_file, snapshot


def check():
    checks = {}
    for case, photo_count in [('single', 1), ('interruption', 3)]:
        base = DATA / case
        conn = sqlite3.connect((base / 'home/state.sqlite3').as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            assets = [dict(r) for r in conn.execute('SELECT * FROM assets')]
            approvals = [dict(r) for r in conn.execute('SELECT * FROM approvals')]
            tasks = [dict(r) for r in conn.execute('SELECT * FROM tasks')]
            ingest_steps = [dict(r) for r in conn.execute("SELECT * FROM task_steps WHERE stage='ingest'")]
        finally:
            conn.close()
        expected_sidecars = {a['dest_rel_path']: a['sha256'] for a in assets if a['kind'] == 'sidecar'}
        actual_sidecars = {str(p.relative_to(base / 'library')): hash_file(p)
                           for p in (base / 'library').rglob('*')
                           if p.is_file() and p.suffix.lower() in {'.xmp', '.acr'}}
        calls = [json.loads(s) for s in (OUT / f'{case}-real-calls.jsonl').read_text().splitlines()]
        imports = [c for c in calls if c.get('event') == 'tool_call_finished' and c['tool'] == 'import_photos']
        imports_by_path = dict(Counter(c['arguments']['source_path'] for c in imports))
        task, = tasks
        item = {'state': task['state'], 'run_count': task['run_count'],
                'approval_count': len(approvals),
                'approval_preserved': len(approvals) == 1 and approvals[0]['revoked_at'] is None and approvals[0]['plan_digest'] == task['plan_digest'],
                'ingest_completed_once': len(ingest_steps) == 1 and ingest_steps[0]['state'] == 'COMPLETED',
                'source_unchanged': snapshot(base / 'source') == json.loads((OUT / f'{case}-source-before.json').read_text()),
                'sidecar_set_and_hashes_preserved': actual_sidecars == expected_sidecars,
                'expected_sidecars': expected_sidecars, 'actual_sidecars': actual_sidecars,
                'import_calls_by_exact_path': imports_by_path,
                'all_imports_confirmed_one_photo': all(c.get('result', {}).get('success') is True and c['result'].get('imported') == 1 for c in imports),
                'all_library_asset_hashes_match': all(hash_file(base / 'library' / a['dest_rel_path']) == a['sha256'] for a in assets)}
        checks[case] = item
        assert item['state'] == 'COMPLETED' and item['approval_preserved'] and item['ingest_completed_once'], item
        assert item['source_unchanged'] and item['sidecar_set_and_hashes_preserved'] and item['all_library_asset_hashes_match'], item
        assert len(imports) == photo_count and list(imports_by_path.values()) == [1] * photo_count, item
        assert item['all_imports_confirmed_one_photo'], item
        assert all(Path(p).is_relative_to(base / 'library') for p in imports_by_path), item
    for case in ['tamper-preset', 'tamper-export']:
        calls = [json.loads(s) for s in (OUT / f'{case}-real-calls.jsonl').read_text().splitlines()]
        calls_started = [c for c in calls if c.get('event') == 'tool_call_started']
        checks[case] = {'real_lightroom_calls': len(calls_started)}
        assert not calls_started
    return checks


if __name__ == '__main__':
    try:
        checks = check()
    except BaseException as exc:
        (OUT / 'final-inventory.json').write_text(json.dumps({'result': 'FAIL', 'error': repr(exc), 'traceback': traceback.format_exc()}, indent=2))
        raise
    (OUT / 'final-inventory.json').write_text(json.dumps({'result': 'PASS', 'time': time.time(), 'checks': checks}, indent=2))
    print('PASS: source/library hashes, sidecars, unique real imports, one approval, ingest once')
