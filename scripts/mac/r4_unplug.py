"""Exercise interruption and recovery for a read-only card test folder.

Run with --help. A child copies only after human approval; no power-off is tested.
"""
import argparse
import json
import math
from datetime import datetime, timezone
import os
import shlex
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cetacea import db
from cetacea.core import Workbench
from cetacea.ingest.pathsafe import read_hash
from r_common import assert_clean, compare_snapshots, desensitize, guard_writes, resolve_mount_by_uuid, snapshot_tree
from r3_fullcard import (SCOPE_NOTE, approvals, guard, plan, prepare, readback, save, save_result, scope, wait_approval)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-uuid', required=True); p.add_argument('--source-subdir', required=True)
    t = p.add_mutually_exclusive_group(); t.add_argument('--target-volume-uuid'); t.add_argument('--target-base', default='/Volumes/Cetacea Studio')
    p.add_argument('--home'); p.add_argument('--out', default='evidence/mac-r4')
    p.add_argument('--confirm-card-readonly', action='store_true', required=True)
    p.add_argument('--scenario', choices=['unplug', 'kill-process'], default='unplug')
    p.add_argument('--max-files', type=int); p.add_argument('--lease-wait-timeout', type=float, default=1200)
    p.add_argument('--pull-timeout', type=float, default=600)
    p.add_argument('--reinsert-timeout', type=float, default=1800); p.add_argument('--approval-timeout', type=float, default=1800)
    p.add_argument('--poll-interval', type=float, default=.05)
    p.add_argument('--inter-file-delay', type=float, default=0, help='Pause between files, when no .part exists; cannot create a mid-file window and is usually unnecessary with --throttle-mbps')
    p.add_argument('--throttle-mbps', type=float, help='Test-only source read limit in decimal MB/s (positive; default off)')
    return p


THROTTLE_NOTE = 'Source reads were deliberately slowed by this test script (test-induced throttle); throughput figures from this run say nothing about product speed.'


class ThrottledReader:
    def __init__(self, stream, mbps):
        self.stream = stream
        self.rate = mbps * 1_000_000
        self.next_time = time.monotonic()

    def read(self, n=-1):
        data = self.stream.read(n)
        self.next_time += len(data) / self.rate
        time.sleep(max(0, self.next_time - time.monotonic()))
        return data

    def __getattr__(self, name): return getattr(self.stream, name)
    def __enter__(self): self.stream.__enter__(); return self
    def __exit__(self, *args): return self.stream.__exit__(*args)


class CopierOSProxy:
    def __init__(self, mbps): self.mbps = mbps
    def __getattr__(self, name): return getattr(os, name)
    def fdopen(self, fd, mode, *args, **kwargs):
        stream = os.fdopen(fd, mode, *args, **kwargs)
        return ThrottledReader(stream, self.mbps) if mode == 'rb' else stream


def child(home, task_id, target, mount, delay, throttle_mbps):
    if throttle_mbps is not None:
        import cetacea.ingest.copier as copier
        copier.os = CopierOSProxy(throttle_mbps)
    def hook(stage, rel):
        if stage == 'after_commit' and delay: time.sleep(delay)
    w = Workbench(home, fault_hook=hook)
    with guard_writes([Path(target), Path(home)], [Path(mount)]):
        result = w.execute(task_id)
    print(result['state'], flush=True)
    return 0 if result['state'] == 'COMPLETED' else 1


def files_state(w, task):
    library = Path(w.config['library_root'])
    tmp = library / '.cetacea-tmp' / task['task_id']
    parts = []
    for p in sorted(tmp.glob('*.part')):
        try: parts.append({'path': str(p.relative_to(library)), 'size': p.stat().st_size})
        except FileNotFoundError: pass
    published = []
    for f in task['plan']['files']:
        path = library / f['dest_rel_path']
        if path.exists():
            actual = read_hash(path)
            published.append({'rel_path': f['rel_path'], 'sha256': actual, 'expected_sha256': f['sha256'], 'ok': actual == f['sha256'] and path.stat().st_size == f['size']})
    return {'parts': parts, 'published': published, 'half_final': any(not x['ok'] for x in published)}


def state(w, task_id):
    with db.connect(w.home) as c:
        steps = [dict(r) for r in c.execute('SELECT * FROM task_steps WHERE task_id=?', (task_id,))]
    return {'task': w.get_task(task_id), 'assets': w.list_assets(task_id=task_id), 'steps': steps}


def observe_copy(proc, w, task, interval):
    last = {}
    while proc.poll() is None:
        current = {x['path']: x['size'] for x in files_state(w, task)['parts']}
        if any(size > 0 and size > last.get(path, size) for path, size in current.items()): return current
        last = current
        time.sleep(min(interval, .1))
    return False


def run(args, mount_resolver=resolve_mount_by_uuid, approval_waiter=wait_approval, lease_expirer=None):
    mount_for_output = Path(mount_resolver(args.source_uuid)).resolve(strict=True)
    out = Path(args.out).resolve()
    if out == mount_for_output or out.is_relative_to(mount_for_output):
        raise ValueError('Evidence output must be outside the source card')
    out.mkdir(parents=True, exist_ok=True)
    mapping = {str(Path.home()): '<HOME>', args.source_uuid: '<UUID>'}
    throttle = {'throttled': args.throttle_mbps is not None, 'throttle_mbps': args.throttle_mbps, 'throttle_note': THROTTLE_NOTE if args.throttle_mbps is not None else None}
    result = {**scope(args), 'status': 'FAIL_STOPPED', 'scenario': args.scenario, **throttle, 'inter_file_delay': args.inter_file_delay, 'part_in_progress_at_interruption': False, 'part_sizes_at_interruption': []}
    proc = None
    exception_class = None
    try:
        if args.max_files is not None and args.max_files < 1: raise ValueError('max-files must be positive')
        if (not all(math.isfinite(x) for x in (args.inter_file_delay, args.poll_interval, args.pull_timeout, args.reinsert_timeout)) or args.inter_file_delay < 0 or args.poll_interval <= 0 or args.pull_timeout <= 0 or args.reinsert_timeout <= 0 or (args.throttle_mbps is not None and (not math.isfinite(args.throttle_mbps) or args.throttle_mbps <= 0))): raise ValueError('Invalid timing or throttle')
        mount, device, source, target, home, mapping = prepare(args, mount_resolver, 'R4')
        def check(): guard(args, mount_resolver, mount, device)
        check(); before = snapshot_tree(source); check(); save(out, 'pre-inventory.json', before, mapping)
        w = Workbench.init(home, target / 'library', target / 'preview')
        task = plan(w, source, args.max_files); check()
        for f in task['plan']['files']:
            if before['files'].get(f['rel_path'], {}).get('sha256') != f['sha256']: raise RuntimeError('Inventory and plan differ')
        watched_rel = f".cetacea-tmp/{task['task_id']}"
        save(out, 'plan.json', {'task': task, 'max_files': args.max_files, 'inter_file_delay': args.inter_file_delay, 'watched_temp_dir_rel': watched_rel, **throttle}, mapping)
        print(f'WATCHING: {watched_rel} under TARGET', flush=True)
        print(f"Files: {len(task['plan']['files'])}; bytes: {task['plan']['total_bytes']}; task: {task['task_id']}; digest: {task['plan_digest']}", flush=True)
        print('python -m cetacea.cli --home ' + shlex.quote(str(home)) + ' approve ' + shlex.quote(task['task_id']) + ' ' + shlex.quote(task['plan_digest']), flush=True)
        approval = approval_waiter(w, task, args.approval_timeout, args.poll_interval)
        save(out, 'approval.json', approval, mapping); check()
        log = home / 'child.log'
        with log.open('w') as stream:
            child_args = {'home': str(home), 'task_id': task['task_id'], 'target': str(target), 'mount': str(mount), 'delay': args.inter_file_delay, 'throttle_mbps': args.throttle_mbps}
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', json.dumps(child_args)], stdout=stream, stderr=subprocess.STDOUT)
            observed = observe_copy(proc, w, task, args.poll_interval)
            if not observed:
                proc.wait(); result.update(status='INTERRUPTION_NOT_ACHIEVED', notes=['Copy completed before progress was observed; try --throttle-mbps 3.'])
            else:
                if args.scenario == 'kill-process':
                    os.kill(proc.pid, signal.SIGKILL); proc.wait(timeout=30)
                    captured = files_state(w, task)
                else:
                    print('NOW PULL THE CARD (eject physically)', flush=True)
                    marker(out, 'PULL_NOW', task['task_id'], max(observed.values()))
                    deadline = time.monotonic() + args.pull_timeout
                    while time.monotonic() < deadline:
                        try: check()
                        except Exception: break
                        if proc.poll() is not None: raise RuntimeError('Child exited before card removal was observed')
                        time.sleep(min(args.poll_interval, .1))
                    else: raise TimeoutError('Card removal not observed')
                    captured = files_state(w, task)
                    proc.wait(timeout=60)
                expected_sizes = {f'{n}.part': item['size'] for n, item in enumerate(task['plan']['files'])}
                result.update(part_in_progress_at_interruption=any(0 < x['size'] < expected_sizes.get(Path(x['path']).name, 0) for x in captured['parts']), part_sizes_at_interruption=captured['parts'])
                save(out, 'interruption-state.json', {**state(w, task['task_id']), 'child_exit_code': proc.returncode, 'child_output': log.read_text(errors='replace')}, mapping)
                save(out, 'after-interruption-files.json', captured, mapping)
                if args.scenario == 'unplug':
                    print('REINSERT THE SAME CARD', flush=True)
                    marker(out, 'REINSERT_NOW', task['task_id'], max((x['size'] for x in captured['parts']), default=0))
                    deadline = time.monotonic() + args.reinsert_timeout
                    while time.monotonic() < deadline:
                        try:
                            check(); break
                        except Exception: time.sleep(args.poll_interval)
                    else: raise TimeoutError('Same card must return at the original mountpoint')
                check(); after_interrupt = snapshot_tree(source); check()
                compare = compare_snapshots(before, after_interrupt)
                save(out, 'reinsert-inventory-compare.json', compare, mapping)
                if lease_expirer: lease_expirer(w, task)
                deadline = time.monotonic() + args.lease_wait_timeout
                while True:
                    w.recover(); current = w.get_task(task['task_id'])
                    if current['state'] != 'RUNNING': break
                    if time.monotonic() >= deadline: raise TimeoutError('Lease did not expire')
                    time.sleep(min(15, max(args.poll_interval, deadline - time.monotonic())))
                save(out, 'recover.json', {'task': current, 'lease_expired_by': 'test_hook' if lease_expirer else 'natural'}, mapping)
                rows = approvals(w, task['task_id'])
                if len(rows) != 1 or rows[0]['revoked_at'] is not None or rows[0]['plan_digest'] != task['plan_digest'] or current['plan_digest'] != task['plan_digest']: raise RuntimeError('Approval or plan changed')
                check()
                with guard_writes([target, home], [mount]):
                    finished = w.retry(task['task_id']) if current['state'] == 'FAILED' else w.execute(task['task_id']) if current['state'] == 'PAUSED' else current
                save(out, 'retry-result.json', finished, mapping); check()
                reads = readback(w, task, before); save(out, 'final-readback.json', reads, mapping)
                after = snapshot_tree(source); check(); comparison = compare_snapshots(before, after)
                save(out, 'source-compare.json', comparison, mapping)
                remaining = files_state(w, task)
                locks = [str(p.relative_to(target)) for p in target.rglob('*.cetacea-lock')]
                library = Path(w.config['library_root']); allowed = {f['dest_rel_path'] for f in task['plan']['files']}
                extras = [str(p.relative_to(library)) for p in library.rglob('*') if p.is_file() and str(p.relative_to(library)) not in allowed]
                unexpected = [p for p in extras if not (Path(p).parent.name == '.cetacea' and Path(p).name.startswith('import-manifest-run') and p.endswith('.json'))]
                result.update(status='PASS' if finished['state'] == 'COMPLETED' and all(x['ok'] for x in reads) and not captured['half_final'] and not remaining['parts'] and not locks and not unexpected and comparison['identical'] and compare['identical'] else 'FAIL',
                              final_state=finished['state'], approvals=len(approvals(w, task['task_id'])), remaining_parts=remaining['parts'], locks=locks, additional_library_files=extras, unplanned_files=unexpected)
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            proc.kill(); proc.wait()
        exception_class = type(exc).__name__
        result['traceback'] = traceback.format_exc()
    save_result(out, result, mapping, exception_class)
    text = desensitize(f"# R4 {result['status']}\n\nscope: test-folder-only\nsource_subdir: {args.source_subdir}\nout_of_scope_content_not_listed: true\n{SCOPE_NOTE}\nScenario: {args.scenario}. Real power-off is out of scope.\nthrottled: {str(throttle['throttled']).lower()}\nthrottle_mbps: {args.throttle_mbps if args.throttle_mbps is not None else 'null'}\n{THROTTLE_NOTE if args.throttle_mbps is not None else ''}\n", mapping)
    assert_clean(text)
    with (out / 'README.md').open('x', encoding='utf-8') as stream: stream.write(text)
    assert_clean(out / 'README.md')
    return result


def marker(out, name, task_id, part_size):
    value = {'timestamp': datetime.now(timezone.utc).isoformat(), 'task_id': task_id, 'part_size': part_size}
    assert_clean(value)
    with (out / name).open('x', encoding='utf-8') as stream: stream.write(json.dumps(value) + '\n')
    assert_clean(out / name)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        if len(sys.argv) != 3: raise ValueError('Expected one child JSON argument')
        return child(**json.loads(sys.argv[2]))
    return 0 if run(parser().parse_args())['status'] == 'PASS' else 1

if __name__ == '__main__': sys.exit(main())
