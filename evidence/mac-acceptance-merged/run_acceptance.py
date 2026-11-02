"""Explicitly triggered Mac acceptance; test catalog and public test copies only.

No product patches, fake backend responses, clock changes or lease writes.
The optional server gate merely pauses between real calls so the operator can
quit the TEST Lightroom session. Do not run against a production catalog.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from PIL import Image

from cetacea import config, db
from cetacea.core import Workbench, LIGHTROOM_ASSET_LEASE_SECONDS
from cetacea.lightroom import RealLightroomMcpAdapter
from cetacea.preview import expected

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'evidence/mac-acceptance-merged'
DATA = ROOT / 'acceptance-data/mac-acceptance-merged'
RAW = ROOT / 'acceptance-data/card-cc0/Nikon-Z6.NEF'
RAW_HASH = '8ca94584578b35a422744c1a610174ce37df0691588edfdecaec3111b3fbbb02'
CATALOG = ROOT.parent / 'cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat'
COMMAND = ['/opt/homebrew/bin/node', str(ROOT.parent / 'cetacea-workbench/.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js')]
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n')


def hash_file(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): {'sha256': hash_file(p),
            'size': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns,
            'inode': p.stat().st_ino} for p in root.rglob('*') if p.is_file()}


def catalog_guard(case):
    pids = subprocess.check_output(['pgrep', '-x', 'Adobe Lightroom Classic'], text=True).split()
    assert len(pids) == 1, 'Ambiguous Lightroom process'
    fds = subprocess.check_output(['lsof', '-p', pids[0], '-Fn'], text=True)
    catalogs = sorted({s[1:] for s in fds.splitlines() if s.startswith('n') and s.endswith('.lrcat')})
    save(f'{case}-catalog-guard.json', {'time': time.time(), 'pid': pids[0], 'open_catalog_paths': catalogs,
                                      'expected': str(CATALOG), 'catalog_content_read': False})
    assert catalogs == [str(CATALOG)], 'Refuse: designated test catalog is not the sole catalog'


def setup(case, count=1):
    base = DATA / case
    base.mkdir(parents=True, exist_ok=False)
    source = base / 'source'
    source.mkdir()
    assert hash_file(RAW) == RAW_HASH
    # Make fresh public-fixture copies before registering the read-only source.
    with os.fdopen(os.open(RAW, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
        raw = f.read()
    for i in range(count):
        with (source / f'public-{i+1}.NEF').open('xb') as f:
            f.write(raw)
    (source / 'existing.XMP').write_bytes(b'Public fixture sidecar sentinel; preserve exactly.\n')
    (source / 'existing.ACR').write_bytes(b'Public fixture ACR sentinel; preserve exactly.\n')
    w = Workbench.init(base / 'home', base / 'library', base / 'preview')
    cfg = config.load(w.home)
    cfg['lightroom'] = {'adapter': 'real_mcp', 'command': COMMAND}
    cfg['preview'] = {'max_edge': 1600, 'quality': 85}
    config.save(w.home, cfg)
    w = Workbench(w.home)
    w.add_source('public-source', source)
    w.create_order('test-order', 'Merged branch public RAW acceptance only')
    w.add_photographer('tester', 'Test operator')
    w.add_preset('test-preset', 'Cetacea Phase1 Test +0.50', lightroom_name='Cetacea Phase1 Test +0.50')
    assert w.adapter.mock is False
    save(f'{case}-source-before.json', snapshot(source))
    return w


def approve(w, planned, case):
    # Current user expressly authorized these test approvals. This is the human
    # operator CLI, never a tool offered to the AI MCP principal.
    args = [sys.executable, '-m', 'cetacea.cli', '--home', str(w.home), '--json',
            'approve', planned['task_id'], planned['plan_digest']]
    p = subprocess.run(args, capture_output=True, text=True)
    save(f'{case}-approval.json', {'command': args, 'exit_code': p.returncode,
                                  'stdout': p.stdout, 'stderr': p.stderr})
    assert p.returncode == 0, p.stderr


def database(w):
    with db.connect(w.home) as c:
        return {table: [dict(row) for row in c.execute('SELECT * FROM ' + table)]
                for table in ['tasks', 'task_steps', 'assets', 'previews', 'approvals', 'audit_log']}


async def invoke(session, case, tool, args):
    entry = {'time': time.time(), 'tool': tool, 'arguments': args}
    try:
        result = await session.call_tool(tool, args)
        entry['response'] = result.model_dump(mode='json', exclude_none=True)
        body = result.structured_content
        if body is None:
            body = json.loads(next(x.text for x in result.content if x.type == 'text'))
        return result, body
    except BaseException as exc:
        entry['exception'] = repr(exc)
        raise
    finally:
        entry['seconds'] = time.time() - entry['time']
        with (OUT / f'{case}-mcp.jsonl').open('a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def server_params(w, case, gate=False):
    env = {'CETACEA_ACCEPTANCE_HOME': str(w.home),
           'CETACEA_ACCEPTANCE_LOG': str(OUT / f'{case}-real-calls.jsonl')}
    if gate:
        env.update({'CETACEA_ACCEPTANCE_GATE_TOOL': 'get_photo_metadata',
                    'CETACEA_ACCEPTANCE_GATE_OCCURRENCE': '3',
                    'CETACEA_ACCEPTANCE_GATE_TIMEOUT_SECONDS': '300',
                    'CETACEA_ACCEPTANCE_GATE_READY': str(OUT / 'interruption-gate.ready.json'),
                    'CETACEA_ACCEPTANCE_GATE_RELEASE': str(OUT / 'interruption-gate.release')})
    return StdioServerParameters(command=sys.executable,
                                args=[str(OUT / 'mcp_capture_server.py')], env=env)


async def scenario(case):
    retry = case == 'retry-resume'
    name = 'interruption' if retry else case
    w = Workbench(DATA / name / 'home') if retry else setup(name, 3 if name == 'interruption' else 1)
    catalog_guard(case)
    async with stdio_client(server_params(w, name, gate=name == 'interruption' and not retry)) as streams:
        async with ClientSession(*streams, read_timeout_seconds=1200) as session:
            await session.initialize()
            if retry:
                planned = json.loads((OUT / 'interruption-plan.json').read_text())
            else:
                result, planned = await invoke(session, name, 'photo_plan_import', {
                    'order_id': 'test-order', 'photographer_id': 'tester',
                    'source_id': 'public-source', 'preset_id': 'test-preset'})
                save(f'{name}-plan.json', planned)
                assert not result.is_error and planned['state'] == 'WAITING_APPROVAL'
                assert planned['plan']['stages'] == STAGES and 'lightroom' in planned['plan']
                approve(w, planned, name)
            tid = planned['task_id']
            if case.startswith('tamper-'):
                planned_assets = database(w)['assets']
                cfg = config.load(w.home)
                if case == 'tamper-preset': cfg['presets']['test-preset']['lightroom_name'] = 'Changed after approval'
                else: cfg['preview']['quality'] = 70
                config.save(w.home, cfg)
                result, done = await invoke(session, name, 'photo_execute_import', {'task_id': tid})
                state = Workbench(w.home).get_task(tid)
                rows = database(w)
                checks = {'expected_rejection': result.is_error and done.get('code') == 'PERMISSION_DENIED',
                          'message': done.get('message'), 'state': state['state'],
                          'no_work': not rows['task_steps'] and rows['assets'] == planned_assets and not rows['previews'],
                          'library_empty': not any((w.home.parent / 'library').rglob('*')),
                          'preview_empty': not any((w.home.parent / 'preview').rglob('*')),
                          'approval_count': len(rows['approvals']), 'mock': False}
                checks['source_unchanged'] = snapshot(w.home.parent / 'source') == json.loads((OUT / f'{name}-source-before.json').read_text())
                save(f'{name}-database.json', rows)
                save(f'{name}-checks.json', checks)
                assert checks['expected_rejection'] and checks['state'] == 'WAITING_APPROVAL' and checks['no_work']
                assert checks['library_empty'] and checks['preview_empty'] and checks['approval_count'] == 1
                assert checks['source_unchanged']
                return checks
            result, done = await invoke(session, case, 'photo_retry_task' if retry else 'photo_execute_import', {'task_id': tid})
            save(f'{case}-result.json', done)
            rows = database(w)
            save(f'{case}-database.json', rows)
            source_ok = snapshot(w.home.parent / 'source') == json.loads((OUT / f'{name}-source-before.json').read_text())
            assert not result.is_error, done
            if name == 'interruption' and not retry:
                registered = [a for a in rows['assets'] if a['lr_photo_id']]
                checks = {'expected_induced_failure': done['state'] == 'FAILED',
                          'error': done['error'], 'registered_count': len(registered),
                          'approval_count': len(rows['approvals']), 'source_unchanged': source_ok,
                          'library_snapshot': snapshot(w.home.parent / 'library')}
                save('interruption-before-retry-checks.json', checks)
                assert checks['expected_induced_failure'] and len(registered) == 1 and source_ok
                assert checks['approval_count'] == 1
                return checks
            assert done['state'] == 'COMPLETED', done
            result, verification = await invoke(session, case, 'photo_verify_preview', {'task_id': tid})
            save(f'{case}-verify-preview.json', verification)
            assert not result.is_error and verification['status'] == 'OK' and verification['mock'] is False
    assets = rows['assets']
    photos, _ = expected(assets)
    checks = {'state': done['state'], 'source_unchanged': source_ok, 'mock': False,
              'approval_count': len(rows['approvals']), 'previews': [],
              'completed_stages': [r['stage'] for r in rows['task_steps'] if r['state'] == 'COMPLETED'],
              'destination_hashes_match': all(hash_file(Path(w.config['library_root']) / a['dest_rel_path']) == a['sha256'] for a in assets),
              'asset_statuses': [{k:a[k] for k in ['asset_id','status','lr_status','preset_applied','mock']} for a in assets]}
    for p in rows['previews']:
        with Image.open(p['path']) as image:
            image.load()
            checks['previews'].append({'asset_id': p['asset_id'], 'dimensions': image.size,
                                        'sha256_matches': hash_file(p['path']) == p['sha256']})
    # Independent real Lightroom readback of the exact public library copies.
    metadata = await asyncio.to_thread(RealLightroomMcpAdapter(command=COMMAND).call_tool, 'get_photo_metadata', {
        'photo_ids': [str(Path(w.config['library_root']) / a['dest_rel_path']) for a in photos],
        'sections': ['developSettings']})
    save(f'{case}-develop-readback.json', metadata)
    checks['exposure_readback'] = [p['developSettings']['exposure'] for p in metadata['photos']]
    if retry:
        before = json.loads((OUT / 'interruption-before-retry-checks.json').read_text())
        checks['library_unchanged_by_retry'] = snapshot(w.home.parent / 'library') == before['library_snapshot']
        checks['approval_count_unchanged'] = len(rows['approvals']) == before['approval_count'] == 1
        checks['registration_retry_steps'] = [r for r in rows['task_steps'] if r['stage'] == 'lr_register']
    calls = [json.loads(line) for line in (OUT / f'{name}-real-calls.jsonl').read_text().splitlines()]
    lease_samples = [dict(sample, tool=call['tool'], call_id=call['call_id'])
                     for call in calls if call.get('event') == 'tool_call_started'
                     for sample in call.get('database_before', {}).get('tasks', [])
                     if sample.get('state') == 'RUNNING' and sample.get('lease_until')]
    checks['lightroom_asset_lease_constant_seconds'] = LIGHTROOM_ASSET_LEASE_SECONDS
    checks['lease_samples'] = lease_samples
    save(f'{case}-checks.json', checks)
    assert source_ok and checks['destination_hashes_match'] and checks['approval_count'] == 1
    assert set(checks['completed_stages']) == set(STAGES)
    assert all(a['status'] == 'VERIFIED' for a in assets)
    assert all(a['lr_status'] == 'EXPORTED' and a['mock'] == 0 for a in photos)
    assert all(p['sha256_matches'] and max(p['dimensions']) == 1600 for p in checks['previews'])
    assert len(checks['previews']) == len(photos) and checks['exposure_readback'] == [0.5] * len(photos)
    assert LIGHTROOM_ASSET_LEASE_SECONDS == 920
    for tool in ['get_photo_metadata', 'apply_develop_preset', 'export_photos']:
        fresh = [s['lease_remaining_seconds'] for s in lease_samples if s['tool'] == tool]
        assert fresh and 919 <= max(fresh) <= 920.1, (tool, fresh)
    if retry:
        assert checks['library_unchanged_by_retry'] and checks['approval_count_unchanged']
        last = checks['registration_retry_steps'][-1]
        assert last['succeeded'] == 2 and last['skipped'] == 1 and last['failed'] == 0
    return checks


if __name__ == '__main__':
    case = sys.argv[1]
    assert case in {'single', 'tamper-preset', 'tamper-export', 'interruption', 'retry-resume'}
    try:
        checks = asyncio.run(scenario(case))
        checks_file = 'interruption-before-retry-checks.json' if case == 'interruption' else f'{case}-checks.json'
        save(f'{case}-verdict.json', {'result': 'PASS', 'checks_file': checks_file, 'time': time.time()})
        print(json.dumps({'case': case, 'result': 'PASS'}, ensure_ascii=False), flush=True)
    except BaseException as exc:
        save(f'{case}-verdict.json', {'result': 'FAIL', 'error': repr(exc), 'traceback': traceback.format_exc(), 'time': time.time()})
        traceback.print_exc()
        sys.exit(1)
