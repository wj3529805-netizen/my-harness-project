"""R6 scoped Lightroom acceptance runner.

Only DCIM/142NZ6_3 is in scope. Never inspect 143NZ6_3, a production
catalog, or a NAS. Source media is always read-only.
"""
import argparse
import os
import json
import plistlib
import shlex
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
    p.add_argument('--mode', choices=('r3', 'r4'), required=True)
    p.add_argument('--source-uuid')
    p.add_argument('--source-subdir', type=scope_argument, default=SCOPE)
    p.add_argument('--confirm-card-readonly', action='store_true', required=True)
    p.add_argument('--expect-nef', type=int, default=9)
    p.add_argument('--expect-jpg', type=int, default=9)
    p.add_argument('--target-base', default='/Volumes/Cetacea Studio')
    p.add_argument('--out')
    p.add_argument('--lightroom', choices=('real', 'mock'), default='real')
    p.add_argument('--lightroom-node', default='/opt/homebrew/bin/node')
    p.add_argument('--lightroom-mcp-index', default=default_mcp_index())
    p.add_argument('--lightroom-test-catalog-path')
    p.add_argument('--lightroom-process-name', default='Adobe Lightroom Classic')
    p.add_argument('--preset-name', default='Cetacea Phase1 Test +0.50')
    p.add_argument('--approval-timeout', type=float, default=1800)
    p.add_argument('--approval-interval', type=float, default=1)
    p.add_argument('--preflight-only', action='store_true')
    p.add_argument('--reader-note', default='Reader changed from USB to built-in SD reader')
    return p


def source_uuid(args, environ=None):
    environ = os.environ if environ is None else environ
    value = args.source_uuid or environ.get('CETACEA_SOURCE_UUID')
    if not value:
        raise ValueError('source UUID must be supplied by argument or CETACEA_SOURCE_UUID')
    return value


def scope_listing(mount, subdir=SCOPE, expect_nef=9, expect_jpg=9):
    # Validate before resolving or making any filesystem call.
    scope_argument(subdir)
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
            if suffix not in ('.nef', '.jpg', '.jpeg'):
                unexpected.append(entry.name)
                continue
            files.append({'rel_path': entry.name, 'size': entry.stat(follow_symlinks=False).st_size,
                          'kind': 'nef' if suffix == '.nef' else 'jpg'})
    counts = {kind: sum(f['kind'] == kind for f in files) for kind in ('nef', 'jpg')}
    if unexpected or counts != {'nef': expect_nef, 'jpg': expect_jpg}:
        raise ValueError('Scope mismatch: expected exactly the requested NEF and JPG counts and no other files')
    return sorted(files, key=lambda f: f['rel_path'])


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


def run(args, mount_resolver=resolve_mount_by_uuid, approval_waiter=r3.wait_approval,
        command_runner=None, reader_runner=None, adapter=None):
    # Validate the scope before any filesystem access, including output creation.
    scope_argument(args.source_subdir)
    if args.mode == 'r4':
        raise ValueError('R4+LR 已推迟，未准备为可运行')
    args.source_uuid = source_uuid(args)
    if not args.confirm_card_readonly:
        raise ValueError('Explicit read-only confirmation required')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = Path(args.out or f'evidence/mac-r6/{args.mode}/run-{stamp}').absolute()
    mapping = {args.source_uuid: '<UUID>', args.source_uuid.upper(): '<UUID>', str(Path.home()): '<HOME>'}
    result = {'mode': args.mode, 'status': 'FAIL_STOPPED', 'real_lightroom': args.lightroom == 'real',
              'mock': args.lightroom == 'mock', 'scope': 'test-folder-only', 'scope_subdir': SCOPE,
              'counts': {}, 'checks': {}, 'preflight_checks': [], 'failed_step': None, 'failures': [], 'notes': [],
              'reader_changed_from_usb': True, 'volume_uuid_sha256_prefix': uuid_prefix(args.source_uuid)}
    guards, messages = [], []
    created = False
    execution_started = False
    def save(name, value): r3.save(out, name, value, mapping)
    def check(name, value, reason):
        result['checks'][name] = {'passed': bool(value), 'reason': reason}
        if not value: result['failures'].append(reason)
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
        source = None
        listing = None
        def list_scope():
            nonlocal source, listing
            if args.expect_nef != 9 or args.expect_jpg != 9:
                raise ValueError('invalid expected counts')
            volume_guard(args.source_uuid, mount, mount.stat().st_dev, mount_resolver)
            listing = scope_listing(mount, args.source_subdir, args.expect_nef, args.expect_jpg)
            source = scoped_source(mount, args.source_subdir)
            mapping[str(source)] = '<CARD>/' + SCOPE
            result['counts'] = {'nef': 9, 'jpg': 9}
            return True
        attempt('scope_listing_9nef_9jpg', '检查测试文件夹是否恰有 9 个 NEF 和 9 个 JPG，且无其他文件', list_scope, card_ok)
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
            target = target_base / ('Cetacea-R6-Test-' + stamp)
            target.mkdir(exist_ok=False)
            home = Path(tempfile.mkdtemp(prefix='cetacea-r6-'))
            mapping[str(target)] = '<TARGET>'; mapping[str(home)] = '<HOME>'
            w = Workbench.init(home, target / 'library', target / 'preview')
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
            lookup = {a['asset_id']: a for a in assets}
            preview_rows = []
            for p in previews:
                a = lookup[p['asset_id']]
                manifest = json.loads((Path(p['path']).parent / 'preview-manifest.json').read_text())
                item = next(x for x in manifest['previews'] if x['asset_id'] == p['asset_id'])
                pair = lookup.get(item.get('paired_jpg_asset_id'))
                preview_rows.append({'rel_path': a['rel_path'], 'width': p['width'], 'height': p['height'], 'sha256': p['sha256'], 'library_sha256': a['sha256'], 'paired_jpg': pair['rel_path'] if pair else None, 'mock': bool(p['mock'])})
            save('previews.json', preview_rows)
            verification = w.verify_preview(task['task_id']); save('verify-preview.json', verification)
            metadata = []
            missing = 0
            if args.lightroom == 'real':
                independent = RealLightroomMcpAdapter(command=command)
                for a in raw:
                    path = str(safe(w.config['library_root'], a['dest_rel_path']))
                    response = independent.call_tool('get_photo_metadata', {'photo_ids': [path], 'sections': ['developSettings']})
                    missing += len(response.get('missing', []))
                    for photo in response.get('photos', []):
                        metadata.append({'filename': Path(path).name, 'fileFormat': photo.get('fileFormat'), 'dimensions': photo.get('dimensions'), 'exposure': photo.get('developSettings', {}).get('exposure')})
            save('lightroom-readback.json', {'mock': args.lightroom == 'mock', 'photos': metadata, 'missing_count': missing})
            lib_inventory = {'files': {f['dest_rel_path']: {} for f in task['plan']['files'] if f['kind'] == 'raw'}}
            subtype = r3.subtype_report(Path(w.config['library_root']), lib_inventory)
            save('nef-subtype-report.json', subtype); result['nef_subtypes'] = subtype['counts']
            stage_map = {s['stage']: s for s in steps}
            check('task_completed', finished['state'] == 'COMPLETED', 'Task must complete')
            check('verified_library', len(reads) == 18 and all(x['ok'] for x in reads), 'All 18 destination hashes must match source')
            check('ingest', stage_map.get('ingest', {}).get('state') == 'COMPLETED' and stage_map['ingest']['succeeded'] == 18, 'Ingest must complete 18 files')
            check('lightroom_stages', all(stage_map.get(s, {}).get('state') == 'COMPLETED' and stage_map[s]['succeeded'] == 9 for s in STAGES[1:]), 'All Lightroom and preview stages must complete nine photos')
            check('raw_and_jpg', len(raw) == len(jpg) == 9 and all(a['lr_status'] == 'EXPORTED' and a['preset_applied'] == 'test-preset' and a['lr_photo_id'] and bool(a['mock']) == (args.lightroom == 'mock') for a in raw) and all(not a['lr_photo_id'] for a in jpg), 'Only nine RAW files must be registered, preset and exported')
            check('previews', len(preview_rows) == 9 and all(max(p['width'], p['height']) == 1600 and p['paired_jpg'] for p in preview_rows) and verification['status'] == 'OK' and verification['mock'] == (args.lightroom == 'mock'), 'Nine 1600-pixel paired previews must independently verify')
            check('readback', args.lightroom == 'mock' or (len(metadata) == 9 and missing == 0 and all(p['exposure'] == 0.5 for p in metadata)), 'Real Lightroom must independently read back nine exposures of 0.5; mock is a rehearsal')
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
        if created:
            save('catalog-guard.json', guards)
            r3.save_result(out, result, mapping)
            for name, content in [('README.md', f"# R6 {result['status']}\n\nMode: {args.lightroom}; scope: {SCOPE}. Reader changed from USB. Mock is not real Lightroom verification.\n"), ('console.txt', '\n'.join(messages) + '\n')]:
                clean = desensitize(content, mapping)
                try: assert_clean(clean)
                except ValueError: clean = 'Details withheld because they contain identifying information.\n'
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
