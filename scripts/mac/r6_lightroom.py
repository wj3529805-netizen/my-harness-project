"""R6 scoped Lightroom acceptance runner.

Each mode is locked to its designated test folder. Source media is read-only.
"""
import argparse
import os
import json
import plistlib
import shlex
import sqlite3
import resource
import signal
import time
from contextlib import contextmanager
from urllib.parse import quote
import tempfile
from datetime import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from r_common import (scoped_source, resolve_mount_by_uuid, volume_guard, uuid_prefix,
                      snapshot_tree, compare_snapshots, guard_writes, desensitize, assert_clean)
import r3_fullcard as r3
from cetacea import config, db
from cetacea.core import Workbench
from cetacea.lightroom import MockLightroomAdapter, RealLightroomMcpAdapter
from cetacea.ingest.pathsafe import read_hash, safe

SCOPE = 'DCIM/142NZ6_3'
LARGE_SCOPE = 'DCIM/143NZ6_3'


def scope_argument(value):
    if value != SCOPE:
        raise argparse.ArgumentTypeError('source scope is hard locked to ' + SCOPE)
    return value


def default_mcp_index(repo=None):
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
    suffix = '.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js'
    candidates = [repo / suffix, repo.parent / 'cetacea-workbench' / suffix]
    return str(next((path for path in candidates if path.exists()), candidates[0]))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('r3', 'r4', 'large'), required=True)
    p.add_argument('--source-uuid')
    p.add_argument('--source-subdir')
    p.add_argument('--confirm-card-readonly', action='store_true', required=True)
    p.add_argument('--expect-nef', type=int)
    p.add_argument('--expect-jpg', type=int)
    p.add_argument('--target-base', default='/Volumes/Cetacea Studio')
    p.add_argument('--out')
    homes = p.add_mutually_exclusive_group()
    homes.add_argument('--home-dir')
    homes.add_argument('--home-on-target', action='store_true')
    p.add_argument('--rejudge', action='store_true')
    p.add_argument('--rejudge-home')
    p.add_argument('--rejudge-task')
    p.add_argument('--rejudge-from')
    p.add_argument('--lightroom', choices=('real', 'mock'), default='real')
    p.add_argument('--lightroom-node', default='/opt/homebrew/bin/node')
    p.add_argument('--lightroom-mcp-index', default=default_mcp_index())
    p.add_argument('--lightroom-test-catalog-path')
    p.add_argument('--lightroom-process-name', default='Adobe Lightroom Classic')
    p.add_argument('--preset-name', default='Cetacea Phase1 Test +0.50')
    p.add_argument('--lr-sample', default='all')
    p.add_argument('--max-runtime-s', type=float, default=14400)
    p.add_argument('--approval-timeout', type=float, default=1800)
    p.add_argument('--approval-interval', type=float, default=1)
    p.add_argument('--preflight-only', action='store_true')
    p.add_argument('--reader-note', default='Reader changed from USB to built-in SD reader')
    return p


def validate_home_dir(value, mount, out, target_base, target):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('Home must be absolute and not a symlink')
    resolved = path.resolve()
    if resolved.is_relative_to(mount) or resolved.is_relative_to(out.resolve()):
        raise ValueError('Home must be outside the card and evidence directory')
    # Cover the planned roots and roots of other runs on the target volume.
    roots = [target / 'library', target / 'preview']
    if resolved.is_relative_to(target_base):
        parts = resolved.relative_to(target_base).parts
        if len(parts) >= 2 and parts[0].startswith('Cetacea-R6-Test-') and parts[1] in ('library', 'preview'):
            raise ValueError('Home must be outside library and preview roots')
    if any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise ValueError('Home must be outside library and preview roots')
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise ValueError('Existing home must be an empty directory')
        ancestor = path
    else:
        if not path.parent.is_dir():
            raise ValueError('Home parent must be an existing directory')
        ancestor = path.parent
    if ancestor.stat().st_dev == mount.stat().st_dev:
        raise ValueError('Home must be on a different device from the card')
    return resolved


def source_uuid(args, environ=None):
    environ = os.environ if environ is None else environ
    value = args.source_uuid or environ.get('CETACEA_SOURCE_UUID')
    if not value:
        raise ValueError('source UUID must be supplied by argument or CETACEA_SOURCE_UUID')
    return value


def scope_listing(mount, subdir=SCOPE, expect_nef=9, expect_jpg=9, *, allowed_scope=SCOPE):
    # Validate before resolving or making any filesystem call.
    if subdir != allowed_scope or allowed_scope not in (SCOPE, LARGE_SCOPE):
        raise argparse.ArgumentTypeError('source scope is hard locked to ' + allowed_scope)
    for component in (Path(mount) / 'DCIM', Path(mount) / subdir):
        if component.is_symlink():
            raise ValueError('Scope path must not contain symlinks')
    source = scoped_source(mount, subdir)
    files, unexpected = [], []
    with os.scandir(source) as entries:
        for entry in entries:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                unexpected.append(entry.name)
                continue
            if entry.name == '.DS_Store' or entry.name.startswith('._'):
                # Preflight cannot read AppleDouble magic. Formal scanning must
                # validate these candidates before any task is created.
                continue
            suffix = Path(entry.name).suffix.lower()
            if entry.name == 'NC_FLLST.DAT':
                kind = 'other'
            elif suffix in ('.nef', '.jpg', '.jpeg'):
                kind = 'nef' if suffix == '.nef' else 'jpg'
            else:
                unexpected.append(entry.name)
                continue
            files.append({'rel_path': entry.name, 'size': entry.stat(follow_symlinks=False).st_size,
                          'kind': kind})
    counts = {kind: sum(f['kind'] == kind for f in files) for kind in ('nef', 'jpg', 'other')}
    if unexpected or counts['nef'] != expect_nef or counts['jpg'] != expect_jpg or counts['other'] > 1:
        raise ValueError('Scope mismatch: expected requested NEF and JPG counts and optional NC_FLLST.DAT')
    return sorted(files, key=lambda f: f['rel_path'])


def other_never_in_lightroom(assets, previews, paired_ids, steps, adapter_calls, readback_paths, expected=9):
    others = [a for a in assets if a['kind'] == 'other']
    identifiers = {a['asset_id'] for a in others}
    references = identifiers | {a['rel_path'] for a in others} | {a['dest_rel_path'] for a in others if a['dest_rel_path']}
    evidence = json.dumps([adapter_calls, readback_paths, [s['detail_json'] for s in steps if s['stage'].startswith('lr_')]])
    return (all(not a['lr_photo_id'] and not a['lr_status'] and not a['preset_applied'] for a in others)
            and all(p['asset_id'] not in identifiers for p in previews)
            and not identifiers.intersection(paired_ids)
            and all(ref not in evidence for ref in references)
            and all(any(s['stage'] == stage and s['state'] == 'COMPLETED' and s['succeeded'] == expected for s in steps)
                    for stage in ('lr_register', 'lr_preset', 'lr_export')))


def preview_evidence(previews, assets, task, preview_root):
    lookup = {a['asset_id']: a for a in assets}
    manifests, rows, paired_ids = {}, [], []
    try:
        for p in previews:
            directory = safe(preview_root, f"{task['order_id']}/{task['photographer_id']}/{task['batch_id']}/{task['task_id']}/run-{p['run']}")
            path = Path(p['path'])
            if not path.is_absolute() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError('Preview path outside its run directory')
            safe(preview_root, str(path.relative_to(Path(preview_root))))
            if p['run'] not in manifests:
                manifests[p['run']] = json.loads((directory / 'preview-manifest.json').read_text())
                paired_ids.extend(x.get('paired_jpg_asset_id') for x in manifests[p['run']]['previews'])
            item = next(x for x in manifests[p['run']]['previews'] if x['asset_id'] == p['asset_id'])
            a = lookup[p['asset_id']]
            pair = lookup.get(item.get('paired_jpg_asset_id'))
            rows.append({'rel_path': a['rel_path'], 'width': p['width'], 'height': p['height'], 'sha256': p['sha256'], 'library_sha256': a['sha256'], 'paired_jpg': pair['rel_path'] if pair else None, 'mock': bool(p['mock'])})
        return rows, paired_ids, True, list(manifests.values())
    except (OSError, ValueError, KeyError, StopIteration, TypeError):
        return rows, paired_ids, False, list(manifests.values())


def catalog_guard(expected, process_name='Adobe Lightroom Classic', runner=None, label='preflight'):
    if not Path(expected).is_absolute() or not str(expected).endswith('.lrcat'):
        raise ValueError('Expected test catalog must be an absolute .lrcat path')
    runner = runner or (lambda args: subprocess.check_output(args, text=True))
    try:
        pids = runner(['pgrep', '-x', process_name]).split()
    except subprocess.CalledProcessError as exc:
        if exc.returncode != 1:
            raise
        pids = []
    record = {'label': label, 'pid': pids[0] if len(pids) == 1 else None,
              'open_lrcat_count': 0, 'matches_expected': False, 'process_count': len(pids)}
    if len(pids) == 1:
        lines = runner(['lsof', '-p', pids[0], '-Fn']).splitlines()
        catalogs = {line[1:] for line in lines if line.startswith('n') and line.endswith('.lrcat')}
        record.update(open_lrcat_count=len(catalogs), matches_expected=catalogs == {str(expected)})
    return record


def preset_probe(adapter, name):
    response = adapter.call_tool('list_develop_presets', {'query': name, 'limit': 5})
    presets = response.get('presets')
    if not isinstance(presets, list):
        raise ValueError('Invalid preset response')
    matches = sum(isinstance(p, dict) and p.get('name') == name for p in presets)
    count = response.get('count')
    return {'preset_found': type(count) is int and count >= 1 and matches > 0,
            'matching_count': matches}



STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']


def reader_info(mount, runner=None):
    runner = runner or (lambda args: subprocess.check_output(args))
    info = plistlib.loads(runner(['diskutil', 'info', '-plist', str(mount)]))
    keys = ('BusProtocol', 'Internal', 'MediaName', 'IORegistryEntryName',
            'FilesystemType', 'Ejectable', 'RemovableMedia', 'VolumeName')
    return {k: info.get(k) for k in keys}


class RawLightroomWorkbench(Workbench):
    """Exclude standalone JPEGs from Lightroom and its preview expectations."""
    _lr_view = False

    def list_assets(self, *args, **kwargs):
        assets = super().list_assets(*args, **kwargs)
        if not self._lr_view:
            return assets
        raw_stems = {str(Path(a['rel_path']).with_suffix('')) for a in assets if a['kind'] == 'raw'}
        return [a for a in assets if a['kind'] != 'jpeg' or str(Path(a['rel_path']).with_suffix('')) in raw_stems]

    def _lightroom_stage(self, task, stage):
        self._lr_view = True
        try:
            return super()._lightroom_stage(task, stage)
        finally:
            self._lr_view = False

    def verify_preview(self, task_id):
        previous = self._lr_view
        self._lr_view = True
        try:
            return super().verify_preview(task_id)
        finally:
            self._lr_view = previous


def run(args, mount_resolver=resolve_mount_by_uuid, approval_waiter=r3.wait_approval,
        command_runner=None, reader_runner=None, adapter=None):
    expected_scope = LARGE_SCOPE if args.mode == 'large' else SCOPE
    args.source_subdir = args.source_subdir or expected_scope
    if args.source_subdir != expected_scope:
        raise argparse.ArgumentTypeError('source scope is hard locked to ' + expected_scope)
    if args.mode == 'large':
        if args.expect_nef is None or args.expect_jpg is None or args.expect_nef <= 0 or args.expect_jpg <= 0:
            raise ValueError('large mode requires positive --expect-nef and --expect-jpg')
    else:
        args.expect_nef = 9 if args.expect_nef is None else args.expect_nef
        args.expect_jpg = 9 if args.expect_jpg is None else args.expect_jpg
    if args.lr_sample != 'all':
        raise ValueError('Lightroom sampling is not supported by the workbench; use --lr-sample all')
    if args.max_runtime_s <= 0:
        raise ValueError('--max-runtime-s must be positive')
    if args.rejudge:
        return rejudge(args, mount_resolver, command_runner, adapter)
    started_wall = time.monotonic()
    if args.mode == 'r4':
        raise ValueError('R4+LR 已推迟，未准备为可运行')
    args.source_uuid = source_uuid(args)
    if not args.confirm_card_readonly:
        raise ValueError('Explicit read-only confirmation required')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = Path(args.out or f'evidence/mac-r6/{args.mode}/run-{stamp}').absolute()
    mapping = {args.source_uuid: '<UUID>', args.source_uuid.upper(): '<UUID>', str(Path.home()): '<HOME>'}
    result = {'mode': args.mode, 'status': 'FAIL_STOPPED', 'real_lightroom': args.lightroom == 'real',
              'mock': args.lightroom == 'mock', 'scope': 'test-folder-only', 'scope_subdir': expected_scope,
              'counts': {}, 'checks': {}, 'preflight_checks': [], 'failed_step': None, 'failures': [], 'notes': [],
              'reader_changed_from_usb': True, 'volume_uuid_sha256_prefix': uuid_prefix(args.source_uuid)}
    location = 'custom' if args.home_dir else 'target' if args.home_on_target else 'tmp'
    result.update(home_persistent=location != 'tmp', home_location=location, home='<RUN_HOME>')
    if location == 'tmp':
        result['notes'].append('The temporary home <RUN_HOME> may be purged on reboot.')
    guards, messages = [], []
    created = False
    execution_started = False
    def save(name, value): r3.save(out, name, value, mapping)
    def check(name, value, reason):
        result['checks'][name] = {'passed': bool(value), 'reason': reason}
        if not value: result['failures'].append(reason)
    old_handler = signal.getsignal(signal.SIGALRM)
    def runtime_timeout(signum, frame):
        raise TimeoutError('maximum runtime exceeded')
    signal.signal(signal.SIGALRM, runtime_timeout)
    signal.setitimer(signal.ITIMER_REAL, args.max_runtime_s)
    try:
        # Resolve the card before creating evidence so a known card is never written.
        step = 'card_mount'
        mount = None
        mount_error = None
        try:
            mount = Path(mount_resolver(args.source_uuid)).resolve(strict=True)
        except Exception as exc:
            mount_error = exc
        step = 'evidence_output'
        if mount is not None and out.resolve().is_relative_to(mount):
            raise ValueError('Evidence output must be outside card')
        out.mkdir(parents=True, exist_ok=False); created = True
        checks = []
        def record(name, passed, hint, exc=None, skipped=False):
            item = {'name': name, 'passed': bool(passed), 'hint': hint if not passed else ''}
            if skipped:
                item['skipped'] = True
            elif not passed:
                failure = name + ': ' + (type(exc).__name__ + ' — ' if exc else '') + hint
                result['failures'].append(failure)
                messages.append(failure)
                if result['failed_step'] is None:
                    result['failed_step'] = name
            checks.append(item)
            return bool(passed)
        def attempt(name, hint, fn, dependencies=True):
            if not dependencies:
                return record(name, False, '前置检查未通过，已跳过', skipped=True), None
            try:
                value = fn()
                return record(name, bool(value), hint), value
            except Exception as exc:
                return record(name, False, hint, exc), None
        card_ok = record('card_mounted', mount is not None, '无法解析卡的挂载点，请检查 UUID 和卡是否已挂载', mount_error)
        if card_ok:
            mapping[str(mount)] = '<CARD>'
        target_base = None
        def resolve_target():
            nonlocal target_base
            target_base = Path(args.target_base).resolve(strict=True)
            if not target_base.is_dir():
                raise NotADirectoryError()
            mapping[str(target_base)] = '<TARGET>'
            return True
        target_ok, _ = attempt('target_volume_present', '目标卷未挂载，请接上并确认路径（--target-base）', resolve_target)
        def different_device():
            return not (target_base == mount or target_base.is_relative_to(mount) or
                        (mount_resolver is resolve_mount_by_uuid and target_base.stat().st_dev == mount.stat().st_dev))
        attempt('target_on_different_device', '目标卷必须与源卡位于不同设备', different_device, card_ok and target_ok)
        attempt('evidence_outside_card', '证据目录必须位于源卡之外', lambda: not out.resolve().is_relative_to(mount), card_ok)
        target = target_base / ('Cetacea-R6-Test-' + stamp) if target_ok else None
        custom_home = None
        if args.home_dir:
            def check_home():
                nonlocal custom_home
                custom_home = validate_home_dir(args.home_dir, mount, out, target_base, target)
                mapping[str(custom_home)] = '<RUN_HOME>'
                return True
            attempt('home_dir_safe', 'home 必须使用绝对路径，位于卡和证据目录之外及不同设备；不能位于 library 或 preview 内，且必须为空目录或有已存在的父目录，不能是符号链接', check_home, card_ok and target_ok)
        else:
            record('home_dir_safe', True, '', skipped=True)
        source = None
        listing = None
        def list_scope():
            nonlocal source, listing
            if args.mode != 'large' and (args.expect_nef != 9 or args.expect_jpg != 9):
                raise ValueError('invalid expected counts')
            volume_guard(args.source_uuid, mount, mount.stat().st_dev, mount_resolver)
            listing = scope_listing(mount, args.source_subdir, args.expect_nef, args.expect_jpg, allowed_scope=expected_scope)
            source = scoped_source(mount, args.source_subdir)
            mapping[str(source)] = '<CARD>/' + expected_scope
            result['counts'] = {kind: sum(f['kind'] == kind for f in listing) for kind in ('nef', 'jpg', 'other')}
            result['lr_scope'] = {'mode': 'all', 'count': result['counts']['nef'], 'total_raw': result['counts']['nef']}
            return True
        attempt('scope_listing_9nef_9jpg' if args.mode != 'large' else 'scope_listing_expected_counts', '检查测试文件夹是否恰有 9 个 NEF 和 9 个 JPG，可选一个精确命名的 NC_FLLST.DAT，不能有其他文件', list_scope, card_ok)
        real = args.lightroom == 'real'
        node_ok, _ = attempt('node_binary_exists', 'Node 不存在，请用 --lightroom-node 指定运行时', lambda: Path(args.lightroom_node).is_file()) if real else (record('node_binary_exists', True, ''), None)
        index_ok, _ = attempt('mcp_index_exists', 'MCP index.js 不存在，请用 --lightroom-mcp-index 指定', lambda: Path(args.lightroom_mcp_index).is_file()) if real else (record('mcp_index_exists', True, ''), None)
        token_ok, _ = attempt('bridge_token_exists', 'bridge token 不存在，请启动并配置 Lightroom MCP bridge', lambda: (Path.home() / '.config/lightroom-mcp/token').is_file()) if real else (record('bridge_token_exists', True, ''), None)
        guard = None
        try:
            if real:
                expected = args.lightroom_test_catalog_path or '/__missing_test_catalog__.lrcat'
                guard = catalog_guard(expected, args.lightroom_process_name, command_runner, 'preflight')
                if not args.lightroom_test_catalog_path:
                    guard['matches_expected'] = False
            else:
                guard = {'label': 'preflight', 'pid': None, 'open_lrcat_count': None, 'matches_expected': True, 'mock': True}
            guards.append(guard)
            process_ok = record('lightroom_single_process', guard.get('process_count', 1 if guard.get('matches_expected') else 0) == 1, '请启动且只运行一个 Lightroom Classic 进程')
            record('catalog_guard_matches_test_catalog', guard['matches_expected'], '请在 Lightroom 中只打开指定的测试 catalog', skipped=not process_ok)
        except Exception as exc:
            guards.append({'label': 'preflight', 'matches_expected': False, 'skipped': True})
            record('lightroom_single_process', False, '无法检查 Lightroom 进程，请确认 Lightroom 已启动', exc)
            record('catalog_guard_matches_test_catalog', False, '前置检查未通过，已跳过', skipped=True)
            process_ok = False
        command = [args.lightroom_node, args.lightroom_mcp_index]
        lr = adapter or (MockLightroomAdapter(size=(1600, 1067)) if not real else RealLightroomMcpAdapter(command=command))
        connected, _ = attempt('mcp_connected', '无法连接 MCP，请检查 Lightroom、bridge 和 token', lambda: lr.status().startswith('Lightroom MCP connected'), node_ok and index_ok and token_ok and process_ok and bool(guard and guard['matches_expected'])) if real else (record('mcp_connected', True, ''), None)
        probe = None
        def check_preset():
            nonlocal probe
            probe = preset_probe(lr, args.preset_name)
            return probe['preset_found']
        if real:
            attempt('preset_found', '未找到指定预设，请在 Lightroom 中创建或指定预设', check_preset, connected)
        else:
            probe = {'preset_found': True, 'matching_count': 1, 'mock': True}
            record('preset_found', True, '')
        result['preflight_checks'] = checks
        save('preflight.json', {'status': 'FAIL_STOPPED' if result['failures'] else 'OK', 'checks': checks,
                                'counts': result['counts'], 'preset': probe,
                                'lightroom': 'MOCK' if not real else ('connected' if connected else 'unavailable')})
        if result['failures']:
            return result
        step = 'reader_info'
        reader = reader_info(mount, reader_runner) if real else {'mock': True}
        reader.update(reader_changed_from_usb=True, note=args.reader_note, volume_uuid_sha256_prefix=uuid_prefix(args.source_uuid))
        save('reader.json', reader)
        device = mount.stat().st_dev
        def volume_check(): volume_guard(args.source_uuid, mount, device, mount_resolver)
        def catalog(label):
            if not real:
                record_guard = {'label': label, 'pid': None, 'open_lrcat_count': None, 'matches_expected': True, 'mock': True}
            else:
                record_guard = catalog_guard(args.lightroom_test_catalog_path, args.lightroom_process_name, command_runner, label)
            guards.append(record_guard)
            if not record_guard['matches_expected']:
                if label != 'after_execute':
                    raise RuntimeError('请在 Lightroom 里只打开测试 catalog')
                check('catalog_guard', False, 'All catalog guards must pass; mock is simulated')
                result['status'] = 'FAIL'
        step = 'preflight_complete'
        if args.preflight_only:
            result['status'] = 'PREFLIGHT_OK_MOCK' if args.lightroom == 'mock' else 'PREFLIGHT_OK'
        else:
            step = 'volume_guard'
            volume_check()
            step = 'scope_inventory'
            before = snapshot_tree(source)
            # Scanner may only discard legitimate metadata; do not silently drop an ordinary file.
            if set(before['files']) != {f['rel_path'] for f in listing}: raise ValueError('Scope changed or invalid metadata')
            save('inventory-before.json', before)
            if args.home_dir:
                custom_home = validate_home_dir(args.home_dir, mount, out, target_base, target)
            target.mkdir(exist_ok=False)
            if args.home_on_target:
                home = target / 'home'
                home.mkdir(exist_ok=False)
            elif custom_home is not None:
                home = custom_home
                if not home.exists():
                    home.mkdir(exist_ok=False)
            else:
                home = Path(tempfile.mkdtemp(prefix='cetacea-r6-'))
            mapping[str(target)] = '<TARGET>'; mapping[str(home)] = '<RUN_HOME>'
            w = (RawLightroomWorkbench if args.mode == 'large' else Workbench).init(home, target / 'library', target / 'preview')
            w.config['lightroom'] = {'adapter': 'mock' if args.lightroom == 'mock' else 'real_mcp', 'command': command}
            w.config['preview'] = {'max_edge': 1600, 'quality': 85}
            config.save(home, w.config); w.adapter = lr
            w.add_source('card', source); w.create_order('r3', 'Test'); w.add_photographer('tester', 'Test')
            w.add_preset('test-preset', lightroom_name=args.preset_name)
            scan = w.scan_source('card')
            if {f['rel_path']: f['sha256'] for f in scan['files']} != {k: v['sha256'] for k, v in before['files'].items()}:
                raise RuntimeError('Inventory and scan differ')
            task = w.plan_import('r3', 'tester', 'card', preset_id='test-preset', stages=STAGES, scan_result=scan)
            save('plan.json', task)
            prompt = 'python -m cetacea.cli --home ' + shlex.quote(str(home)) + ' approve ' + shlex.quote(task['task_id']) + ' ' + shlex.quote(task['plan_digest'])
            print(f"task_id={task['task_id']} plan_digest={task['plan_digest']} approval: {prompt}", flush=True)
            messages.append('Approval command printed (paths omitted from evidence).')
            step = 'approval'
            approval_waiter(w, task, args.approval_timeout, args.approval_interval)
            approval_before = r3.approvals(w, task['task_id'])
            if len(approval_before) != 1 or approval_before[0]['plan_digest'] != task['plan_digest'] or approval_before[0]['revoked_at'] is not None:
                raise RuntimeError('Expected exactly one valid approval')
            step = 'lightroom_process_catalog_guard'
            volume_check(); catalog('before_execute')
            adapter_calls = []
            for method in ('register', 'apply_preset', 'export_jpeg'):
                original = getattr(lr, method)
                def observe(files, *a, _original=original, _method=method, **kw):
                    if time.monotonic() - started_wall >= args.max_runtime_s:
                        raise TimeoutError('maximum runtime exceeded')
                    adapter_calls.append([_method, [(f.asset_id, f.rel_path, str(f.abs_path)) for f in files]])
                    return _original(files, *a, **kw)
                setattr(lr, method, observe)
            with guard_writes([target, home, Path(tempfile.gettempdir())], [mount]):
                step = 'execute'
                execution_started = True
                finished = w.execute(task['task_id'])
            if finished['state'] != 'COMPLETED':
                result['status'] = 'FAIL'
                result['failures'].append('Pipeline failed: ' + str(finished.get('error') or finished['state']))
            step = 'lightroom_process_catalog_guard'
            catalog('after_execute'); volume_check()
            step = 'execution_evidence'
            assets = w.list_assets(task_id=task['task_id'])
            with db.connect(home) as c:
                steps = [dict(x) for x in c.execute('SELECT * FROM task_steps WHERE task_id=?', (task['task_id'],))]
                previews = [dict(x) for x in c.execute('SELECT * FROM previews WHERE task_id=?', (task['task_id'],))]
            approval_after = r3.approvals(w, task['task_id'])
            save('approval.json', {'before': approval_before, 'after': approval_after, 'count': len(approval_after)})
            for asset in assets:
                if asset.get('error'):
                    detail = desensitize(str(asset['error']), mapping)
                    try:
                        assert_clean(detail)
                    except ValueError:
                        detail = 'Error details withheld for privacy; inspect the local task log'
                    result['failures'].append(asset['rel_path'] + ': ' + detail)
            compact_assets = [{k: a[k] for k in ('rel_path', 'kind', 'status', 'lr_status', 'preset_applied', 'mock')} | {'has_lr_photo_id': bool(a['lr_photo_id'])} for a in assets]
            compact_steps = [{k: row[k] for k in ('run', 'stage', 'state', 'succeeded', 'failed', 'skipped', 'started_at', 'ended_at')} for row in steps]
            for row in steps:
                if row['state'] == 'FAILED':
                    result['failures'].append(row['stage'] + ': ' + str(row['failed']) + ' failed')
                    detail = json.loads(row['detail_json'])
                    for item in detail if isinstance(detail, list) else [detail]:
                        if isinstance(item, dict) and item.get('error'):
                            error = desensitize(str(item['error']), mapping)
                            try:
                                assert_clean(error)
                            except ValueError:
                                error = 'Details withheld for privacy; inspect local task log'
                            result['failures'].append(row['stage'] + ' ' + str(item.get('asset_id', '')) + ': ' + error)
            save('database.json', {'task': {k: finished[k] for k in ('task_id','state','run_count','error','plan_digest')}, 'task_steps': compact_steps, 'assets': compact_assets})
            timing = [dict(row, elapsed_seconds=(datetime.fromisoformat(row['ended_at']) - datetime.fromisoformat(row['started_at'])).total_seconds()) for row in compact_steps]
            save('stage-timing.json', timing)
            after = snapshot_tree(source); volume_check(); save('inventory-after.json', after)
            reads = r3.readback(w, task, before)
            save('library-readback.json', reads)
            raw = [a for a in assets if a['kind'] == 'raw']; jpg = [a for a in assets if a['kind'] == 'jpeg']
            preview_rows, paired_ids, manifest_ok, manifests = preview_evidence(previews, assets, task, w.config['preview_root'])
            save('previews.json', preview_rows)
            verification = w.verify_preview(task['task_id']); save('verify-preview.json', verification)
            metadata = []
            missing = 0
            readback_paths = []
            if args.lightroom == 'real':
                independent = RealLightroomMcpAdapter(command=command)
                for a in raw:
                    path = str(safe(w.config['library_root'], a['dest_rel_path']))
                    readback_paths.append(path)
                    response = independent.call_tool('get_photo_metadata', {'photo_ids': [path], 'sections': ['developSettings']})
                    missing += len(response.get('missing', []))
                    for photo in response.get('photos', []):
                        metadata.append({'filename': Path(path).name, 'fileFormat': photo.get('fileFormat'), 'dimensions': photo.get('dimensions'), 'exposure': photo.get('developSettings', {}).get('exposure')})
            save('lightroom-readback.json', {'mock': args.lightroom == 'mock', 'photos': metadata, 'missing_count': missing})
            lib_inventory = {'files': {f['dest_rel_path']: {} for f in task['plan']['files'] if f['kind'] == 'raw'}}
            subtype = r3.subtype_report(Path(w.config['library_root']), lib_inventory)
            save('nef-subtype-report.json', subtype); result['nef_subtypes'] = subtype['counts']
            stage_map = {s['stage']: s for s in steps}
            expected_ingest = len(listing)
            raw_count = result['counts']['nef']
            raw_stems = {str(Path(a['rel_path']).with_suffix('')) for a in raw}
            unpaired = [a for a in jpg if str(Path(a['rel_path']).with_suffix('')) not in raw_stems]
            calls_evidence = json.dumps([adapter_calls, list(getattr(lr, 'calls', [])), manifests, readback_paths])
            check('task_completed', finished['state'] == 'COMPLETED', 'Task must complete')
            check('verified_library', len(reads) == expected_ingest and all(x['ok'] for x in reads), f'All {expected_ingest} destination hashes must match source')
            check('ingest', stage_map.get('ingest', {}).get('state') == 'COMPLETED' and stage_map['ingest']['succeeded'] == expected_ingest, f'Ingest must complete {expected_ingest} files')
            check('lightroom_stages', all(stage_map.get(s, {}).get('state') == 'COMPLETED' and stage_map[s]['succeeded'] == raw_count for s in STAGES[1:]), f'All Lightroom and preview stages must complete {raw_count} photos')
            check('raw_and_jpg', len(raw) == raw_count and len(jpg) == result['counts']['jpg'] and all(a['lr_status'] == 'EXPORTED' and a['preset_applied'] == 'test-preset' and a['lr_photo_id'] and bool(a['mock']) == (args.lightroom == 'mock') for a in raw) and all(not a['lr_photo_id'] for a in jpg), f'Only {raw_count} RAW files must be registered, preset and exported')
            check('other_never_in_lightroom', other_never_in_lightroom(assets, previews, paired_ids, steps, adapter_calls + list(getattr(lr, 'calls', [])) + manifests, readback_paths, raw_count), 'Other assets must never enter Lightroom or paired previews; each Lightroom stage must succeed for nine RAW files')
            check('unpaired_jpg_never_in_lightroom', all(not a['lr_photo_id'] and not a['lr_status'] and not a['preset_applied'] and a['asset_id'] not in paired_ids and all(ref not in calls_evidence for ref in (a['asset_id'], a['rel_path'], a['dest_rel_path'])) for a in unpaired), 'Unpaired JPEGs must never enter Lightroom')
            check('previews', manifest_ok and len(preview_rows) == raw_count and all(max(p['width'], p['height']) == 1600 and (args.mode == 'large' or p['paired_jpg']) for p in preview_rows) and verification['status'] == 'OK' and verification['mock'] == (args.lightroom == 'mock'), f'{raw_count} 1600-pixel previews must independently verify')
            check('readback', args.lightroom == 'mock' or (len(metadata) == raw_count and missing == 0 and all(p['exposure'] == 0.5 for p in metadata)), f'Real Lightroom must independently read back {raw_count} exposures of 0.5; mock is a rehearsal')
            check('approval', len(approval_after) == 1 and approval_before == approval_after and approval_after[0]['plan_digest'] == task['plan_digest'], 'Exactly one unchanged approval')
            check('source_unchanged', compare_snapshots(before, after)['identical'], 'Source inventory must remain unchanged')
            if 'catalog_guard' not in result['checks']:
                check('catalog_guard', len(guards) == 3 and all(g['matches_expected'] for g in guards), 'All catalog guards must pass; mock is simulated')
            result['lightroom_stage_summary'] = compact_steps
            result['status'] = ('PASS_MOCK_NOT_REAL_LIGHTROOM' if args.lightroom == 'mock' else 'PASS') if all(c['passed'] for c in result['checks'].values()) else 'FAIL'
    except Exception as exc:
        if execution_started:
            result['status'] = 'FAIL'
        # Exception text may contain private Lightroom metadata or arbitrary paths.
        detail = desensitize(str(exc), mapping)
        try:
            assert_clean(detail)
        except ValueError:
            detail = 'Details withheld for privacy'
        result['failed_step'] = step
        message = step + ': ' + type(exc).__name__ + ' — 步骤执行失败；请检查本地环境'
        result['failures'].append(message)
        messages.append(message)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if created:
            if args.mode == 'large':
                stage_stats = {}
                for row in locals().get('timing', []):
                    elapsed = row['elapsed_seconds']
                    items = row['succeeded'] + row['failed'] + row['skipped']
                    stage_stats[row['stage']] = {'elapsed_s': elapsed, 'items': items,
                        'items_per_s': items / elapsed if elapsed > 0 else None,
                        's_per_item': elapsed / items if items else None}
                ingest_step = next((row for row in locals().get('steps', []) if row['stage'] == 'ingest'), None)
                ingest_events = json.loads(ingest_step['detail_json']) if ingest_step else []
                ingest_bytes = sum(event['size'] for event in ingest_events if event.get('status') == 'VERIFIED' and not event.get('skipped_verified'))
                if 'ingest' in stage_stats:
                    stage_stats['ingest']['bytes'] = ingest_bytes
                    elapsed = stage_stats['ingest']['elapsed_s']
                    stage_stats['ingest']['mb_per_s'] = ingest_bytes / 1000000 / elapsed if elapsed > 0 else None
                throughput = {'stages': stage_stats, 'total_wall_s': time.monotonic() - started_wall,
                              'peak_rss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                              'peak_rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
                              'notes': ['Per-file ingest timing is unavailable in the database.']}
                result['throughput'] = throughput
                save('throughput.json', throughput)
            save('catalog-guard.json', guards)
            r3.save_result(out, result, mapping)
            home_note = 'The temporary home <RUN_HOME> may be purged on reboot.' if location == 'tmp' else f'Run home: <RUN_HOME> ({location}).'
            for name, content in [('README.md', f"# R6 {result['status']}\n\nMode: {args.lightroom}; scope: {expected_scope}. Reader changed from USB. Mock is not real Lightroom verification.\n\n{home_note}\n"), ('console.txt', '\n'.join(messages) + '\n')]:
                clean = desensitize(content, mapping)
                try: assert_clean(clean)
                except ValueError: clean = 'Details withheld because they contain identifying information.\n'
                (out / name).write_text(clean, encoding='utf-8'); assert_clean(out / name)
    return result


def tree_state(root):
    root = Path(root)
    entries = []
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((rel, 'symlink', os.readlink(path)))
        elif path.is_dir():
            entries.append((rel, 'dir'))
        elif path.is_file():
            entries.append((rel, 'file', path.stat().st_size, read_hash(path)))
        else:
            entries.append((rel, 'other'))
    return entries


def rejudge(args, mount_resolver, command_runner, adapter):
    from cetacea import preview
    from cetacea.core import digest
    if args.mode != 'r3':
        raise ValueError('Rejudge is only available for r3')
    if not all((args.out, args.rejudge_home, args.rejudge_task, args.rejudge_from)) or args.preflight_only:
        raise ValueError('Rejudge requires --out, --rejudge-home, --rejudge-task and --rejudge-from')
    scope_argument(args.source_subdir)
    args.source_uuid = source_uuid(args)
    if not args.confirm_card_readonly:
        raise ValueError('Explicit read-only confirmation required')
    original = Path(args.rejudge_from).resolve(strict=True)
    home = Path(args.rejudge_home).resolve(strict=True)
    out = Path(args.out).resolve()
    if out.exists() or out == original or out.is_relative_to(original) or original.is_relative_to(out) or out == home or out.is_relative_to(home) or home.is_relative_to(out):
        raise ValueError('Rejudge output must be new and separate from original evidence and home')
    mount = Path(mount_resolver(args.source_uuid)).resolve(strict=True)
    if out == mount or out.is_relative_to(mount):
        raise ValueError('Evidence output must be outside card')
    mapping = {args.source_uuid: '<UUID>', args.source_uuid.upper(): '<UUID>', str(Path.home()): '<HOME>', str(home): '<RUN_HOME>', str(mount): '<CARD>', str(original): '<ORIGINAL>'}
    result = {'mode': 'r3', 'status': 'FAIL_STOPPED', 'real_lightroom': args.lightroom == 'real', 'mock': args.lightroom == 'mock', 'scope': 'test-folder-only', 'scope_subdir': SCOPE, 'counts': {}, 'checks': {}, 'preflight_checks': [], 'failed_step': None, 'failures': [], 'notes': ['Offline re-verdict of an already completed run; no stage re-run.', 'adapter_calls_observed: false'], 'adapter_calls_observed': False, 'rejudge': True, 'rejudged_from': original.name, 'task_id': args.rejudge_task}
    guards = []
    def save(name, value): r3.save(out, name, value, mapping)
    def check(name, value, reason):
        result['checks'][name] = {'passed': bool(value), 'reason': reason}
        if not value: result['failures'].append(reason)
    target_base = Path(args.target_base).resolve(strict=True)
    if out == target_base or out.is_relative_to(target_base) or target_base.is_relative_to(out):
        raise ValueError('Rejudge output must be separate from the target')
    out.mkdir(parents=True, exist_ok=False)
    step = 'preflight'
    home_before = target_before = None
    roots = []
    try:
        with guard_writes([out, Path(tempfile.gettempdir())], [mount, home, original, target_base]):
            target = Path(args.target_base).resolve(strict=True)
            mapping[str(target)] = '<TARGET>'
            if not target.is_dir() or target == mount or target.is_relative_to(mount) or (mount_resolver is resolve_mount_by_uuid and target.stat().st_dev == mount.stat().st_dev):
                raise ValueError('Target must be on a different device')
            volume_guard(args.source_uuid, mount, mount.stat().st_dev, mount_resolver)
            if args.expect_nef != 9 or args.expect_jpg != 9: raise ValueError('invalid expected counts')
            listing = scope_listing(mount, args.source_subdir, args.expect_nef, args.expect_jpg)
            source = scoped_source(mount, args.source_subdir)
            result['counts'] = {kind: sum(f['kind'] == kind for f in listing) for kind in ('nef', 'jpg', 'other')}
            cfg = config.load(home)
            roots = [Path(cfg['library_root']).resolve(strict=True), Path(cfg['preview_root']).resolve(strict=True)]
            if any(not root.is_relative_to(target) or out == root or out.is_relative_to(root) or root.is_relative_to(out) for root in roots):
                raise ValueError('Target roots or evidence output are unsafe')
            # An immutable SQLite view cannot include uncheckpointed WAL data.
            wal = home / 'state.sqlite3-wal'
            if wal.exists() and wal.stat().st_size: raise ValueError('Database has an uncheckpointed WAL')
            home_before = {name: read_hash(home / name) for name in ('state.sqlite3', 'config.json')}
            target_before = [tree_state(root) for root in roots]
            real = args.lightroom == 'real'
            if real:
                if not (Path(args.lightroom_node).is_file() and Path(args.lightroom_mcp_index).is_file() and (Path.home() / '.config/lightroom-mcp/token').is_file()):
                    raise ValueError('Lightroom MCP prerequisites missing')
                guard = catalog_guard(args.lightroom_test_catalog_path or '/__missing_test_catalog__.lrcat', args.lightroom_process_name, command_runner, 'rejudge')
                guards.append(guard)
                if guard.get('process_count') != 1 or not guard['matches_expected'] or not args.lightroom_test_catalog_path: raise ValueError('Catalog guard failed')
                lr = adapter or RealLightroomMcpAdapter(command=[args.lightroom_node, args.lightroom_mcp_index])
                if not lr.status().startswith('Lightroom MCP connected') or not preset_probe(lr, args.preset_name)['preset_found']: raise ValueError('MCP or preset unavailable')
            else:
                guards.append({'label': 'rejudge', 'matches_expected': True, 'mock': True})
                lr = adapter or MockLightroomAdapter(size=(1600, 1067))
            save('preflight.json', {'status': 'OK', 'counts': result['counts'], 'lightroom': 'connected' if real else 'MOCK'})
            step = 'execution_evidence'
            uri = 'file:' + quote(str(home / 'state.sqlite3'), safe='/') + '?mode=ro&immutable=1'
            @contextmanager
            def readonly(_home):
                c = sqlite3.connect(uri, uri=True)
                c.row_factory = sqlite3.Row
                try: yield c
                finally: c.close()
            with readonly(home) as c:
                row = c.execute('SELECT * FROM tasks WHERE task_id=?', (args.rejudge_task,)).fetchone()
                if row is None: raise ValueError('Task not found')
                task = dict(row); task['plan'] = json.loads(task['plan_json'])
                assets = [dict(x) for x in c.execute('SELECT * FROM assets WHERE order_id=? AND photographer_id=? AND batch_id=?', (task['order_id'], task['photographer_id'], task['batch_id']))]
                steps = [dict(x) for x in c.execute('SELECT * FROM task_steps WHERE task_id=?', (args.rejudge_task,))]
                previews = [dict(x) for x in c.execute('SELECT * FROM previews WHERE task_id=?', (args.rejudge_task,))]
                approvals = [dict(x) for x in c.execute('SELECT * FROM approvals WHERE task_id=?', (args.rejudge_task,))]
            before = json.loads((original / 'inventory-before.json').read_text())
            approval_original = json.loads((original / 'approval.json').read_text())['after']
            class ReadOnlyView:
                home = Path(args.rejudge_home)
                config = cfg
                adapter = lr
                def get_task(self, task_id): return task
                def list_assets(self, task_id=None): return assets
            view = ReadOnlyView()
            reads = r3.readback(view, task, before)
            after = snapshot_tree(source)
            volume_guard(args.source_uuid, mount, mount.stat().st_dev, mount_resolver)
            rows, pairs, manifest_ok, manifests = preview_evidence(previews, assets, task, cfg['preview_root'])
            old_connect = db.connect
            try:
                db.connect = readonly
                verification = preview.verify(view, task['task_id'])
            finally:
                db.connect = old_connect
            raw = [a for a in assets if a['kind'] == 'raw']; jpg = [a for a in assets if a['kind'] == 'jpeg']
            metadata, readback_paths = [], []
            missing = 0
            if real:
                independent = RealLightroomMcpAdapter(command=[args.lightroom_node, args.lightroom_mcp_index])
                for a in raw:
                    path = str(safe(cfg['library_root'], a['dest_rel_path']))
                    readback_paths.append(path)
                    response = independent.call_tool('get_photo_metadata', {'photo_ids': [path], 'sections': ['developSettings']})
                    missing += len(response.get('missing', []))
                    metadata.extend({'filename': Path(path).name, 'fileFormat': p.get('fileFormat'), 'dimensions': p.get('dimensions'), 'exposure': p.get('developSettings', {}).get('exposure')} for p in response.get('photos', []))
            compact_steps = [{k: s[k] for k in ('run', 'stage', 'state', 'succeeded', 'failed', 'skipped', 'started_at', 'ended_at')} for s in steps]
            compact_assets = [{k: a[k] for k in ('rel_path', 'kind', 'status', 'lr_status', 'preset_applied', 'mock')} | {'has_lr_photo_id': bool(a['lr_photo_id'])} for a in assets]
            save('database.json', {'task': {k: task[k] for k in ('task_id', 'state', 'run_count', 'error', 'plan_digest')}, 'task_steps': compact_steps, 'assets': compact_assets})
            save('library-readback.json', reads); save('previews.json', rows); save('verify-preview.json', verification)
            save('lightroom-readback.json', {'mock': not real, 'photos': metadata, 'missing_count': missing}); save('inventory-after.json', after)
            stage_map = {s['stage']: s for s in steps}; count = len(listing)
            check('task_completed', task['state'] == 'COMPLETED', 'Task must complete')
            check('verified_library', digest(task['plan']) == task['plan_digest'] and len(reads) == count and all(x['ok'] for x in reads), f'All {count} destination hashes must match source')
            check('ingest', stage_map.get('ingest', {}).get('state') == 'COMPLETED' and stage_map['ingest']['succeeded'] == count, f'Ingest must complete {count} files')
            check('lightroom_stages', all(stage_map.get(s, {}).get('state') == 'COMPLETED' and stage_map[s]['succeeded'] == 9 for s in STAGES[1:]), 'All Lightroom and preview stages must complete nine photos')
            check('raw_and_jpg', len(raw) == len(jpg) == 9 and all(a['lr_status'] == 'EXPORTED' and a['preset_applied'] == 'test-preset' and a['lr_photo_id'] and bool(a['mock']) == (not real) for a in raw) and all(not a['lr_photo_id'] for a in jpg), 'Only nine RAW files must be registered, preset and exported')
            check('other_never_in_lightroom', other_never_in_lightroom(assets, previews, pairs, steps, manifests, readback_paths), 'Other assets must never enter Lightroom or paired previews; each Lightroom stage must succeed for nine RAW files')
            check('previews', manifest_ok and len(rows) == 9 and all(max(p['width'], p['height']) == 1600 and p['paired_jpg'] for p in rows) and verification['status'] == 'OK' and verification['mock'] == (not real), 'Nine 1600-pixel paired previews must independently verify')
            check('readback', not real or (len(metadata) == 9 and missing == 0 and all(p['exposure'] == 0.5 for p in metadata)), 'Real Lightroom must independently read back nine exposures of 0.5; mock is a rehearsal')
            check('approval', len(approvals) == 1 and approvals[0]['revoked_at'] is None and approvals[0]['plan_digest'] == task['plan_digest'] and desensitize(approvals, mapping) == approval_original, 'Exactly one unchanged approval')
            check('source_unchanged', compare_snapshots(before, after)['identical'], 'Source inventory must remain unchanged')
            if real:
                guards.append(catalog_guard(args.lightroom_test_catalog_path, args.lightroom_process_name, command_runner, 'after_rejudge'))
            check('catalog_guard', all(g['matches_expected'] and g.get('process_count', 1) == 1 for g in guards), 'All catalog guards must pass; mock is simulated')
            result['lightroom_stage_summary'] = compact_steps
    except Exception as exc:
        result['failed_step'] = step
        result['failures'].append(step + ': ' + type(exc).__name__ + ' — 步骤执行失败；请检查本地环境')
    finally:
        if home_before is not None:
            try: unchanged = home_before == {name: read_hash(home / name) for name in home_before}
            except Exception: unchanged = False
            check('rejudge_home_unchanged', unchanged, 'Home database and config must remain unchanged')
        if target_before is not None:
            try: unchanged = target_before == [tree_state(root) for root in roots]
            except Exception: unchanged = False
            check('rejudge_target_unchanged', unchanged, 'Target trees must remain unchanged')
        if result['failed_step'] == 'execution_evidence': result['status'] = 'FAIL'
        elif result['failed_step'] is None:
            result['status'] = ('PASS' if args.lightroom == 'real' else 'PASS_MOCK_NOT_REAL_LIGHTROOM') if all(c['passed'] for c in result['checks'].values()) else 'FAIL'
        save('catalog-guard.json', guards)
        r3.save_result(out, result, mapping)
        for name, content in [('README.md', f"# R6 {result['status']}\n\nOffline re-verdict; no stage re-run. MOCK is not real Lightroom verification.\n"), ('console.txt', '\n'.join(result['failures']) + '\n')]:
            clean = desensitize(content, mapping); assert_clean(clean)
            (out / name).write_text(clean, encoding='utf-8'); assert_clean(out / name)
    return result


def main():
    p = parser(); args = p.parse_args()
    if args.mode == 'r4':
        print('R4+LR 已推迟，未准备为可运行', file=sys.stderr); return 1
    try:
        result = run(args)
    except ValueError as exc:
        p.error(str(exc))
    return 0 if result['status'] in ('PASS', 'PASS_MOCK_NOT_REAL_LIGHTROOM', 'PREFLIGHT_OK', 'PREFLIGHT_OK_MOCK') else 1


if __name__ == '__main__':
    sys.exit(main())
