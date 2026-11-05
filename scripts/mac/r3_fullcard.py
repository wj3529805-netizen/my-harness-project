"""Measure a read-only test folder import. Run with --help for Mac usage.

Only the specified card subfolder is inspected; target and home must be fresh.
Human CLI approval is mandatory. Evidence is sanitized before writing.
"""
import argparse
import collections
import json
import os
import resource
import shlex
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cetacea import db
from cetacea.core import Workbench, digest
from cetacea.ingest.pathsafe import read_hash, safe
from r_common import (assert_clean, compare_snapshots, desensitize, guard_writes,
                      resolve_mount_by_uuid, scoped_source, snapshot_tree, uuid_prefix,
                      volume_guard, volume_info_by_uuid)
from nef_subtype import classify_file

SCOPE_NOTE = 'The card contains other content deliberately not listed, hashed or recorded.'


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-uuid', required=True)
    p.add_argument('--source-subdir', required=True)
    target = p.add_mutually_exclusive_group()
    target.add_argument('--target-volume-uuid')
    target.add_argument('--target-base', default='/Volumes/Cetacea Studio')
    p.add_argument('--home'); p.add_argument('--out', default='evidence/mac-r3')
    p.add_argument('--confirm-card-readonly', action='store_true', required=True)
    p.add_argument('--min-free-factor', type=float, default=1.2)
    p.add_argument('--lightroom', choices=['mock', 'real'], default='mock')
    p.add_argument('--lightroom-test-catalog-path')
    p.add_argument('--approval-timeout', type=float, default=1800)
    p.add_argument('--poll-interval', type=float, default=1)
    p.add_argument('--allow-missing-subtype', action='store_true')
    p.add_argument('--max-files', type=int, help='Limit planned/ingested NEF files (positive; inventory still covers the selected folder)')
    return p


def save(out, name, obj, mapping):
    clean = desensitize(obj, mapping)
    assert_clean(clean)
    path = out / name
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(clean, indent=2, ensure_ascii=False, default=str) + '\n')
    assert_clean(path)


def save_result(out, result, mapping, exception_class=None):
    try:
        assert_clean(desensitize(result, mapping))
    except ValueError:
        if exception_class is None or 'traceback' not in result:
            raise
        result['traceback'] = f'{exception_class}: traceback withheld: contained identifying path'
    save(out, 'result.json', result, mapping)


def approvals(w, task_id):
    with db.connect(w.home) as c:
        return [dict(row) for row in c.execute('SELECT * FROM approvals WHERE task_id=?', (task_id,))]


def wait_approval(w, task, timeout, interval):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = approvals(w, task['task_id'])
        if len(rows) == 1 and rows[0]['revoked_at'] is None and rows[0]['plan_digest'] == task['plan_digest']:
            return rows[0]
        time.sleep(interval)
    raise TimeoutError('Human approval not received')


def prepare(args, resolver, tag):
    if not args.confirm_card_readonly: raise ValueError('Explicit read-only confirmation required')
    mount = Path(resolver(args.source_uuid)).resolve(strict=True)
    device = mount.stat().st_dev
    source = scoped_source(mount, args.source_subdir)
    base = Path(resolver(args.target_volume_uuid) if args.target_volume_uuid else args.target_base).resolve(strict=True)
    if base == mount or base.is_relative_to(mount) or (resolver is resolve_mount_by_uuid and base.stat().st_dev == device):
        raise ValueError('Target must be on a different device from the card')
    run_dir = base / ('Cetacea-' + tag + '-Test-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    run_dir.mkdir(exist_ok=False)
    if args.home:
        home = Path(args.home).absolute()
        if home.resolve().is_relative_to(mount): raise ValueError('Home must be outside card')
        home.mkdir(parents=False, exist_ok=False)
    else:
        temp_base = Path('/tmp').resolve(strict=True)
        if temp_base == mount or temp_base.is_relative_to(mount) or temp_base.stat().st_dev == device and resolver is resolve_mount_by_uuid:
            raise ValueError('Local temporary directory must be outside the source device')
        home = Path(tempfile.mkdtemp(prefix='cetacea-' + tag.lower() + '-', dir=temp_base))
    mapping = {str(source): '<CARD>/' + args.source_subdir, str(mount): '<CARD>',
               str(run_dir): '<TARGET>', str(base): '<TARGET_BASE>', str(home): '<HOME>',
               str(Path.home()): '<HOME>', args.source_uuid: '<UUID>',
               args.source_uuid.upper(): '<UUID>'}
    if args.target_volume_uuid: mapping[args.target_volume_uuid] = '<UUID>'
    return mount, device, source, run_dir, home, mapping


def guard(args, resolver, mount, device):
    volume_guard(args.source_uuid, mount, device, resolver)


def plan(w, source, max_files=None):
    w.add_source('card', source); w.create_order('r3', 'Test'); w.add_photographer('tester', 'Test')
    scan = w.scan_source('card')
    scan['files'] = [f for f in scan['files'] if f['rel_path'].lower().endswith('.nef')]
    if max_files is not None: scan['files'] = scan['files'][:max_files]
    if not scan['files']: raise ValueError('No NEF files in test folder')
    scan['digest'] = digest([(f['rel_path'], f['size'], f['sha256']) for f in scan['files']])
    return w.plan_import('r3', 'tester', 'card', stages=['ingest'], scan_result=scan)


def readback(w, task, before):
    assets = {a['rel_path']: a for a in w.list_assets(task_id=task['task_id'])}
    results = []
    for f in task['plan']['files']:
        a = assets.get(f['rel_path'], {})
        try: value = read_hash(safe(w.config['library_root'], f['dest_rel_path']))
        except (OSError, ValueError): value = None
        expected = before['files'].get(f['rel_path'], {}).get('sha256')
        results.append({'rel_path': f['rel_path'], 'sha256': value, 'expected_sha256': expected,
                        'asset_status': a.get('status'), 'ok': value is not None and value == expected == f['sha256'] == a.get('sha256') and a.get('status') == 'VERIFIED'})
    return results


def subtype_report(source, before):
    files = {rel: classify_file(source / rel) for rel in before['files'] if rel.lower().endswith('.nef')}
    counts = collections.Counter(v['subtype'] for v in files.values())
    raw = collections.Counter(str(v['tag_0x0093_value']) for v in files.values() if v['tag_0x0093_value'] is not None)
    groups = {kind: [k for k, v in files.items() if v['subtype'] == kind] for kind in sorted(counts)}
    return {'files': files, 'counts': dict(counts), 'raw_values': dict(raw), 'files_by_subtype': groups}


def scope(args):
    return {'scope': 'test-folder-only', 'source_subdir': args.source_subdir,
            'out_of_scope_content_not_listed': True, 'privacy_note': SCOPE_NOTE}


def run(args, mount_resolver=resolve_mount_by_uuid, approval_waiter=wait_approval, volume_info_reader=None):
    mount_for_output = Path(mount_resolver(args.source_uuid)).resolve(strict=True)
    out = Path(args.out).resolve()
    if out == mount_for_output or out.is_relative_to(mount_for_output):
        raise ValueError('Evidence output must be outside the source card')
    out.mkdir(parents=True, exist_ok=True)
    mapping = {str(Path.home()): '<HOME>', args.source_uuid: '<UUID>'}
    notes = ['Single test folder, single run; MB/s depends on reader and target.',
             'Ingest-only run; no Lightroom stage (neither mock nor real) was executed.']
    if args.max_files is not None:
        notes.append(f'Bounded run: ingest plans at most {args.max_files} NEF file(s); inventory and subtype coverage describe the whole selected source folder.')
    result = {**scope(args), 'status': 'FAIL_STOPPED', 'mock': False, 'lightroom': 'NOT_RUN (ingest-only)', 'real_lightroom': False,
              'max_files': args.max_files, 'source_protocol': None, 'source_fs': None,
              'volume_uuid_sha256_prefix': uuid_prefix(args.source_uuid), 'notes': notes}
    exception_class = None
    try:
        if args.max_files is not None and args.max_files < 1: raise ValueError('max-files must be positive')
        if args.lightroom == 'real':
            raise ValueError('Real Lightroom is not supported by this ingest-only runner')
        mount, device, source, target, home, mapping = prepare(args, mount_resolver, 'R3')
        def check(): guard(args, mount_resolver, mount, device)
        if volume_info_reader is None and mount_resolver is resolve_mount_by_uuid:
            volume_info_reader = volume_info_by_uuid
        if volume_info_reader is not None:
            info = volume_info_reader(args.source_uuid)
            if Path(info['MountPoint']).resolve(strict=True) != mount:
                raise RuntimeError('Source metadata mount does not match the resolved card')
            result.update(source_protocol=info.get('Protocol'), source_fs=info.get('FilesystemType'))
            if result['source_protocol'] is None:
                notes.append('Source protocol was not reported by the volume info reader.')
        else:
            notes.append('Source protocol was not queried: a custom mount resolver was supplied without a volume info reader.')
        check(); before = snapshot_tree(source); check()
        save(out, 'inventory-before.json', before, mapping)
        report = subtype_report(source, before); check(); save(out, 'subtype-report.json', report, mapping)
        w = Workbench.init(home, target / 'library', target / 'preview')
        task = plan(w, source, max_files=args.max_files); check()
        total = task['plan']['total_bytes']
        result.update(planned_file_count=len(task['plan']['files']), planned_bytes=total)
        if args.min_free_factor < 1 or shutil.disk_usage(target).free < total * args.min_free_factor: raise RuntimeError('Insufficient target free space')
        for f in task['plan']['files']:
            if before['files'].get(f['rel_path'], {}).get('sha256') != f['sha256']: raise RuntimeError('Inventory and plan differ')
        save(out, 'plan.json', {**task, 'max_files': args.max_files}, mapping)
        print(f"Files: {len(task['plan']['files'])}; bytes: {task['plan']['total_bytes']}; task: {task['task_id']}; digest: {task['plan_digest']}", flush=True)
        print('python -m cetacea.cli --home ' + shlex.quote(str(home)) + ' approve ' + shlex.quote(task['task_id']) + ' ' + shlex.quote(task['plan_digest']), flush=True)
        approval = approval_waiter(w, task, args.approval_timeout, args.poll_interval)
        save(out, 'approval.json', approval, mapping); check()
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        wall, cpu = time.perf_counter(), time.process_time()
        with guard_writes([target, home], [mount]): finished = w.execute(task['task_id'])
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        with db.connect(w.home) as c:
            step = c.execute("SELECT started_at, ended_at FROM task_steps WHERE task_id=? AND stage='ingest' ORDER BY run DESC LIMIT 1", (task['task_id'],)).fetchone()
        ingest_seconds = (datetime.fromisoformat(step['ended_at']) - datetime.fromisoformat(step['started_at'])).total_seconds() if step else 0
        timing = {'wall_seconds': wall, 'cpu_seconds': cpu, 'ingest_wall_seconds': ingest_seconds, 'mb_per_s': total / ingest_seconds / 1_000_000 if ingest_seconds > 0 else None,
                  'method': 'NEF planned bytes / ingest task step timestamp duration / 1,000,000 (decimal MB)',
                  'peak_rss_raw_before': rss_before, 'peak_rss_raw_after': rss_after,
                  'peak_rss_raw_unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
                  'peak_rss_bytes': rss_after * (1 if sys.platform == 'darwin' else 1024)}
        save(out, 'timing.json', timing, mapping); check()
        reads = readback(w, task, before); save(out, 'readback.json', reads, mapping)
        check(); after = snapshot_tree(source); check(); comparison = compare_snapshots(before, after)
        save(out, 'inventory-after.json', after, mapping); save(out, 'source-compare.json', comparison, mapping)
        coverage = {k: 'COVERED' if report['counts'].get(k, 0) else 'NOT_COVERED' for k in ('HE', 'HE_STAR')}
        ok = finished['state'] == 'COMPLETED' and ingest_seconds > 0 and all(r['ok'] for r in reads) and comparison['identical']
        status = 'FAIL' if not ok else 'PARTIAL_NOT_COVERED' if 'NOT_COVERED' in coverage.values() else 'PASS'
        result.update(status=status, coverage=coverage, counts=report['counts'])
    except Exception as exc:
        exception_class = type(exc).__name__
        result['traceback'] = traceback.format_exc()
    save_result(out, result, mapping, exception_class)
    limit_summary = f'max_files: {args.max_files}\n' if args.max_files is not None else ''
    summary = desensitize(f"# R3 {result['status']}\n\nscope: test-folder-only\nsource_subdir: {args.source_subdir}\n{limit_summary}out_of_scope_content_not_listed: true\n{SCOPE_NOTE}\n", mapping)
    assert_clean(summary)
    with (out / 'README.md').open('x', encoding='utf-8') as stream: stream.write(summary)
    assert_clean(out / 'README.md')
    return result


def main():
    result = run(parser().parse_args())
    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__': sys.exit(main())
