"""Exercise interruption and recovery for a read-only card test folder.

Run with --help. A child copies only after human approval; no power-off is tested.
"""
import argparse
import json
import math
from datetime import datetime, timezone
import os
import re
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
    p.add_argument('--hold-mid-file', action='store_true')
    # Linux tests can supply an external flag instead of a real mount probe.
    p.add_argument('--test-only-gone-flag-file', help=argparse.SUPPRESS)
    return p


THROTTLE_NOTE = 'Source reads were deliberately slowed by this test script (test-induced throttle); throughput figures from this run say nothing about product speed.'
HOLD_NOTE = 'Mid-file pause was deliberately induced by this test script (test-induced hold); the source read error after removal is the genuine one.'


class Hold:
    def __init__(self, home, watch_dir, timeout, probe):
        self.home, self.watch_dir, self.timeout, self.probe = Path(home), Path(watch_dir), timeout, probe
        self.state = dict(engaged=False, part_size_at_hold_start=None, started_at=None, released_at=None, released_by='never-engaged', part_size_at_release=None)
        self.write()

    def write(self):
        tmp = self.home / 'hold-state.json.tmp'
        tmp.write_text(json.dumps(self.state), encoding='utf-8')
        os.replace(tmp, self.home / 'hold-state.json')

    def part_size(self):
        for part in self.watch_dir.glob('*.part'):
            try: return part.stat().st_size
            except FileNotFoundError: pass
        return None

    def engage(self):
        self.state.update(engaged=True, part_size_at_hold_start=self.part_size(), started_at=datetime.now(timezone.utc).isoformat(), released_by=None)
        self.write()
        deadline = time.monotonic() + self.timeout
        while True:
            if self.probe(): reason = 'card-removed'; break
            release = self.home / 'hold-release'
            if release.exists():
                reason = 'timeout' if release.read_text(encoding='utf-8').strip() == 'timeout' else 'parent-release'
                break
            if time.monotonic() >= deadline: reason = 'timeout'; break
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
        self.state.update(released_by=reason, released_at=datetime.now(timezone.utc).isoformat(), part_size_at_release=self.part_size())
        self.write()


class ThrottledReader:
    def __init__(self, stream, mbps, hold=None):
        self.stream = stream
        self.hold, self.total = hold, 0
        self.rate = mbps * 1_000_000
        self.next_time = time.monotonic()

    def read(self, n=-1):
        if self.hold and self.total >= 1024 * 1024:
            self.hold.engage(); self.hold = None
        data = self.stream.read(n)
        self.total += len(data)
        self.next_time += len(data) / self.rate
        time.sleep(max(0, self.next_time - time.monotonic()))
        return data

    def __getattr__(self, name): return getattr(self.stream, name)
    def __enter__(self): self.stream.__enter__(); return self
    def __exit__(self, *args): return self.stream.__exit__(*args)


class CopierOSProxy:
    def __init__(self, mbps, hold=None): self.mbps, self.hold, self.first = mbps, hold, True
    def __getattr__(self, name): return getattr(os, name)
    def fdopen(self, fd, mode, *args, **kwargs):
        stream = os.fdopen(fd, mode, *args, **kwargs)
        if mode != 'rb': return stream
        hold = self.hold if self.first and os.fstat(fd).st_size > 1024 * 1024 else None
        self.first = False
        return ThrottledReader(stream, self.mbps, hold)


def child(home, task_id, target, mount, delay, throttle_mbps, hold_mid_file=False, hold_timeout=600, watch_dir=None, test_only_gone_flag_file=None):
    if throttle_mbps is not None:
        import cetacea.ingest.copier as copier
        hold = None
        if hold_mid_file:
            device = os.stat(mount).st_dev
            def gone():
                if test_only_gone_flag_file: return Path(test_only_gone_flag_file).exists()
                try: return not os.path.ismount(mount) or os.stat(mount).st_dev != device
                except OSError: return True
            hold = Hold(home, watch_dir, hold_timeout, gone)
        copier.os = CopierOSProxy(throttle_mbps, hold)
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


def observe_copy(proc, w, task, interval, hold_file=None):
    last = {}
    deadline = time.monotonic() + 120
    while proc.poll() is None and (not hold_file or time.monotonic() < deadline):
        current = {x['path']: x['size'] for x in files_state(w, task)['parts']}
        if hold_file:
            try:
                if json.loads(hold_file.read_text())['engaged']: return current
            except FileNotFoundError: pass
            time.sleep(min(interval, .1)); continue
        if any(size > 0 and size > last.get(path, size) for path, size in current.items()): return current
        last = current
        time.sleep(min(interval, .1))
    return False


DEVICE_ERRORS = {'ENXIO', 'EIO', 'ENODEV', 'ENOENT', 'ESTALE', 'EBADF'}


def hold_verdict(evidence, simulated_by_test=False):
    """Return the hold-specific verdict and reasons, independently of recovery."""
    errors = DEVICE_ERRORS | ({'SOURCE_CHANGED'} if simulated_by_test else set())
    checks = {
        'hold was not confirmed removed': evidence.get('hold_result') == 'HELD_AND_REMOVED',
        'no partial first file was recorded at release': evidence.get('part_in_progress_at_interruption') is True,
        'held file was not the first failed file': evidence.get('held_file_failed_first') is True,
        'child did not exit with an error': evidence.get('child_exit_code') is not None and evidence['child_exit_code'] != 0,
        'first failure was not an accepted read or device error': evidence.get('first_failed_error_class') in errors,
    }
    reasons = [reason for reason, ok in checks.items() if not ok]
    return ('FAIL_UNVERIFIED_INTERRUPTION' if reasons else 'PASS', reasons)


def failure_evidence(task, interruption):
    assets = {asset['asset_id']: asset for asset in interruption['assets']}
    ordered = [assets.get(item['asset_id'], {}) for item in task['plan']['files']]
    failed = [asset for asset in ordered if asset.get('status') == 'FAILED']
    first = failed[0] if failed else {}
    held = task['plan']['files'][0]['rel_path'] if task['plan']['files'] else None
    def error_class(asset):
        match = re.match(r'^([A-Z][A-Z0-9_]*)(?:\s|$)', asset.get('error') or '')
        return match.group(1) if match else None
    later_absent = any(error_class(asset) in {'ENOENT', 'ENXIO', 'EIO', 'ENODEV'} for asset in ordered[1:] if asset.get('status') == 'FAILED')
    return dict(first_failed_file=first.get('rel_path'), first_failed_error_class=error_class(first),
                failed_file_count=len(failed), held_file_rel=held,
                held_file_failed_first=bool(first and first.get('rel_path') == held),
                child_exit_code=interruption['child_exit_code'],
                later_files_failed_because_card_absent='Later files reported card-absence/device errors after removal.' if later_absent else None)


class NoInterruption(Exception):
    pass


def run(args, mount_resolver=resolve_mount_by_uuid, approval_waiter=wait_approval, lease_expirer=None):
    mount_for_output = Path(mount_resolver(args.source_uuid)).resolve(strict=True)
    out = Path(args.out).resolve()
    if out == mount_for_output or out.is_relative_to(mount_for_output):
        raise ValueError('Evidence output must be outside the source card')
    out.mkdir(parents=True, exist_ok=True)
    mapping = {str(Path.home()): '<HOME>', args.source_uuid: '<UUID>'}
    throttle = {'throttled': args.throttle_mbps is not None, 'throttle_mbps': args.throttle_mbps, 'throttle_note': THROTTLE_NOTE if args.throttle_mbps is not None else None}
    hold_fields = dict(hold_mid_file=args.hold_mid_file, hold_engaged=False, hold_released_by=None, hold_result=None, part_size_at_hold_start=None, part_size_at_removal=None, hold_timeout=args.pull_timeout if args.hold_mid_file else None, hold_note=HOLD_NOTE if args.hold_mid_file else None, child_terminated_by_parent=False, part_in_progress_at_interruption=False, parts_after_failure=None, first_failed_file=None, first_failed_error_class=None, failed_file_count=0, held_file_rel=None, held_file_failed_first=False, child_exit_code=None, later_files_failed_because_card_absent=None, simulated_by_test=bool(args.test_only_gone_flag_file))
    result = {**scope(args), **hold_fields, 'status': 'FAIL_STOPPED', 'scenario': args.scenario, **throttle, 'inter_file_delay': args.inter_file_delay, 'part_in_progress_at_interruption': False, 'part_sizes_at_interruption': []}
    proc = None
    exception_class = None
    plan_evidence = None
    log = None
    try:
        if args.hold_mid_file and args.throttle_mbps is None: raise ValueError('--hold-mid-file requires --throttle-mbps')
        if args.hold_mid_file and args.scenario != 'unplug': raise ValueError('--hold-mid-file requires --scenario unplug')
        if args.hold_mid_file and args.pull_timeout > 3000: raise ValueError('--pull-timeout must be <= 3000 with --hold-mid-file')
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
        plan_evidence = {'task': task, 'max_files': args.max_files, 'inter_file_delay': args.inter_file_delay, 'watched_temp_dir_rel': watched_rel, **throttle, **hold_fields}
        print(f'WATCHING: {watched_rel} under TARGET', flush=True)
        print(f"Files: {len(task['plan']['files'])}; bytes: {task['plan']['total_bytes']}; task: {task['task_id']}; digest: {task['plan_digest']}", flush=True)
        print('python -m cetacea.cli --home ' + shlex.quote(str(home)) + ' approve ' + shlex.quote(task['task_id']) + ' ' + shlex.quote(task['plan_digest']), flush=True)
        approval = approval_waiter(w, task, args.approval_timeout, args.poll_interval)
        save(out, 'approval.json', approval, mapping); check()
        log = home / 'child.log'
        with log.open('w') as stream:
            child_args = {'home': str(home), 'task_id': task['task_id'], 'target': str(target), 'mount': str(mount), 'delay': args.inter_file_delay, 'throttle_mbps': args.throttle_mbps, 'hold_mid_file': args.hold_mid_file, 'hold_timeout': args.pull_timeout, 'watch_dir': str(Path(w.config['library_root']) / watched_rel), 'test_only_gone_flag_file': args.test_only_gone_flag_file}
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', json.dumps(child_args)], stdout=stream, stderr=subprocess.STDOUT)
            def hold_state():
                try: return json.loads((home / 'hold-state.json').read_text(encoding='utf-8'))
                except FileNotFoundError: return {}
            def update_hold():
                hs = hold_state()
                result.update(hold_engaged=hs.get('engaged', False), hold_released_by=hs.get('released_by', 'never-engaged'), part_size_at_hold_start=hs.get('part_size_at_hold_start'))
                return hs
            def release(reason): (home / 'hold-release').write_text(reason, encoding='utf-8')
            def no_interruption(reason):
                if proc.poll() is None:
                    release('timeout')
                    cap = task['plan']['total_bytes'] / (args.throttle_mbps * 1_000_000) + len(task['plan']['files']) * args.inter_file_delay + 600
                    try: proc.wait(timeout=cap)
                    except subprocess.TimeoutExpired:
                        result['child_terminated_by_parent'] = True
                        proc.terminate()
                        try: proc.wait(timeout=10)
                        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                update_hold()
                if proc.returncode and not result['child_terminated_by_parent']:
                    raise RuntimeError('Child failed while card was present: ' + log.read_text(errors='replace'))
                result.update(status='INTERRUPTION_NOT_ACHIEVED', hold_result=reason, notes=['card was not removed within --pull-timeout; no interruption occurred; nothing faked' if reason == 'HOLD_TIMEOUT' else 'Hold did not engage before the child finished or within 120 seconds.'])
                save(out, 'interruption-state.json', {**state(w, task['task_id']), 'child_exit_code': proc.returncode, 'child_output': log.read_text(errors='replace')}, mapping)
                save(out, 'after-interruption-files.json', files_state(w, task), mapping)
                raise NoInterruption()
            observed = observe_copy(proc, w, task, args.poll_interval, home / 'hold-state.json' if args.hold_mid_file else None)
            if not observed:
                if args.hold_mid_file:
                    hs = update_hold()
                    no_interruption('HOLD_TIMEOUT' if hs.get('released_by') == 'timeout' else 'NOT_ENGAGED')
                proc.wait(); result.update(status='INTERRUPTION_NOT_ACHIEVED', notes=['Copy completed before progress was observed; try --throttle-mbps 3.'])
            else:
                if args.scenario == 'kill-process':
                    os.kill(proc.pid, signal.SIGKILL); proc.wait(timeout=30)
                    captured = files_state(w, task)
                else:
                    if args.hold_mid_file and update_hold().get('released_by') == 'timeout': no_interruption('HOLD_TIMEOUT')
                    print('NOW PULL THE CARD (eject physically)', flush=True)
                    marker(out, 'PULL_NOW', task['task_id'], max(observed.values()), held=args.hold_mid_file)
                    deadline = time.monotonic() + args.pull_timeout
                    while time.monotonic() < deadline:
                        try: check()
                        except Exception: break
                        if proc.poll() is not None:
                            if not args.hold_mid_file: raise RuntimeError('Child exited before card removal was observed')
                            hs = update_hold()
                            if proc.returncode:
                                race = time.monotonic() + 5
                                while time.monotonic() < race:
                                    try: check()
                                    except Exception: break
                                    time.sleep(min(args.poll_interval, .1))
                                else: raise RuntimeError('Child failed while card was present: ' + log.read_text(errors='replace'))
                                break
                            no_interruption('HOLD_TIMEOUT' if hs.get('released_by') == 'timeout' else 'NOT_ENGAGED')
                        time.sleep(min(args.poll_interval, .1))
                    else:
                        if args.hold_mid_file: no_interruption('HOLD_TIMEOUT')
                        raise TimeoutError('Card removal not observed')
                    if args.hold_mid_file: release('card-removed')
                    captured = files_state(w, task)
                    if args.hold_mid_file: result['hold_result'] = 'HELD_AND_REMOVED'
                    proc.wait(timeout=60)
                    if args.hold_mid_file:
                        hs = update_hold()
                        result['part_size_at_removal'] = hs.get('part_size_at_release')
                        captured = files_state(w, task)
                        result['parts_after_failure'] = captured['parts']
                expected_sizes = {f'{n}.part': item['size'] for n, item in enumerate(task['plan']['files'])}
                if args.hold_mid_file:
                    size = result['part_size_at_removal']
                    result['part_in_progress_at_interruption'] = size is not None and 0 < size < task['plan']['files'][0]['size']
                else:
                    result.update(part_in_progress_at_interruption=any(0 < x['size'] < expected_sizes.get(Path(x['path']).name, 0) for x in captured['parts']), part_sizes_at_interruption=captured['parts'])
                interruption = {**state(w, task['task_id']), 'child_exit_code': proc.returncode, 'child_output': log.read_text(errors='replace')}
                if args.hold_mid_file: result.update(failure_evidence(task, interruption))
                save(out, 'interruption-state.json', interruption, mapping)
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
                # A live runner can outlast its per-file 300-second lease; recover only after it exits.
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
                if args.hold_mid_file and result['status'] == 'PASS':
                    verdict, reasons = hold_verdict(result, bool(args.test_only_gone_flag_file))
                    result['status'] = verdict
                    if reasons: result['notes'] = ['Interruption could not be verified: ' + '; '.join(reasons)]
    except NoInterruption:
        pass
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            proc.kill(); proc.wait()
        if proc is not None and log is not None and log.exists() and not (out / 'interruption-state.json').exists():
            save(out, 'interruption-state.json', {**state(w, task['task_id']), 'child_exit_code': proc.returncode, 'child_output': log.read_text(errors='replace')}, mapping)
        exception_class = type(exc).__name__
        result['traceback'] = traceback.format_exc()
    if args.hold_mid_file and proc is not None:
        result['child_exit_code'] = proc.returncode
        hold_path = home / 'hold-state.json'
        if hold_path.exists(): save(out, 'hold-state.json', json.loads(hold_path.read_text(encoding='utf-8')), mapping)
    if plan_evidence is not None:
        plan_evidence.update({k: result[k] for k in hold_fields})
        save(out, 'plan.json', plan_evidence, mapping)
    save_result(out, result, mapping, exception_class)
    hold_text = '\n'.join(f'{k}: {json.dumps(result[k])}' for k in hold_fields)
    text = desensitize(f"# R4 {result['status']}\n\nscope: test-folder-only\nsource_subdir: {args.source_subdir}\nout_of_scope_content_not_listed: true\n{SCOPE_NOTE}\nScenario: {args.scenario}. Real power-off is out of scope.\nthrottled: {str(throttle['throttled']).lower()}\nthrottle_mbps: {args.throttle_mbps if args.throttle_mbps is not None else 'null'}\n{THROTTLE_NOTE if args.throttle_mbps is not None else ''}\n{hold_text}\n", mapping)
    assert_clean(text)
    with (out / 'README.md').open('x', encoding='utf-8') as stream: stream.write(text)
    assert_clean(out / 'README.md')
    return result


def marker(out, name, task_id, part_size, held=False):
    value = {'timestamp': datetime.now(timezone.utc).isoformat(), 'task_id': task_id, 'part_size': part_size, 'held': held}
    assert_clean(value)
    with (out / name).open('x', encoding='utf-8') as stream: stream.write(json.dumps(value) + '\n')
    assert_clean(out / name)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        if len(sys.argv) != 3: raise ValueError('Expected one child JSON argument')
        return child(**json.loads(sys.argv[2]))
    return 0 if run(parser().parse_args())['status'] == 'PASS' else 1

if __name__ == '__main__': sys.exit(main())
