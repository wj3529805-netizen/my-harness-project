#!/usr/bin/env python3
"""Experimental native folder import; default dry-run, never launches Lightroom."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import register_import_to_lr as register

Error = register.RegistrationError
DOMAIN = 'com.adobe.LightroomClassicCC7'
SAFE_PREFS = {
    'AgImport_importBehavior': 'refInPlace',
    'AgImport_crSettingsID': '<none>',
    'AgImport_metadataPresetID': '<none>',
    'AgImport_keywords': '',
    'AgImport_renamingTokensOn': 0,
    'AgImport_Import_add_photos_to_collection': 0,
    'AgImport_doCopyToBackupFolder': 0,
    'AgImport_generateDNGProxies': 0,
}
# Conservative superset: native folder import can also ingest non-RAW photos
# and supported videos. Never assume register.collect's exclusions apply to LR.
IMPORTABLE = register.RAW | register.JPG | frozenset(
    'avif heic heif hif jxl png psb psd tif tiff mov mp4 m4v avi mts m2ts '
    'm2t mpg mpeg mpe mxf 3gp 3gpp'.split())


def read_prefs(*, runner=subprocess.run):
    """Read only the preferences domain, without opening catalog/Adobe data."""
    result = runner(['defaults', 'export', DOMAIN, '-'], check=True,
                    capture_output=True, timeout=15)
    return parse_prefs(result.stdout)


def parse_prefs(data):
    prefs = plistlib.loads(data)
    if not isinstance(prefs, dict):
        raise Error('Preference plist must be a dictionary')
    return prefs


def prefs_guard(prefs, checked):
    unsafe = []
    for key, expected in SAFE_PREFS.items():
        value = prefs.get(key)
        valid = (type(value) in (int, bool) and value == 0) if expected == 0 else (
            type(value) is str and value == expected)
        if not valid:
            unsafe.append(key)
    if unsafe:
        # Report keys only; never dump an entire personal preferences plist.
        raise Error('Unsafe or missing import preferences: ' + ', '.join(unsafe))
    recursive = prefs.get('AgImport_recursivelyScanFolders')
    if type(recursive) not in (int, bool) or recursive not in (0, 1):
        raise Error('AgImport_recursivelyScanFolders is missing or unrecognized')
    if not checked:
        raise Error('DNG conversion setting is UNVERIFIED (key unknown); inspect native Import settings '
                    'and pass --i-checked-import-settings. Flag cannot bypass unsafe known preferences.')
    return dict(known_preferences_safe=True, recursive=bool(recursive),
                dng_conversion='UNVERIFIED', dng_key='UNKNOWN', human_checked=True,
                sdk_previous_settings_match_preferences='UNVERIFIED')


def inventory(folder, recursive):
    register.no_symlink_directory(folder)
    expected, candidates = [], []
    def walk_error(error):
        raise error
    for directory, dirs, names in os.walk(folder, followlinks=False, onerror=walk_error):
        base = Path(directory)
        # Native import's symlink handling is not established. Refuse instead
        # of following or silently skipping a possible out-of-scope source.
        if any((base / name).is_symlink() for name in dirs + names):
            raise Error('Native folder contains symlinks; refused (native traversal is unverified)')
        relative_parts = base.relative_to(folder).parts
        selected_dir = (folder.name.casefold() not in register.EXCLUDED
                        and not folder.name.startswith('.') and all(
            not part.startswith('.') and part.casefold() not in register.EXCLUDED for part in relative_parts))
        for name in sorted(names):
            path = base / name
            suffix = path.suffix.lower().lstrip('.')
            if name.startswith('._') or not stat.S_ISREG(path.lstat().st_mode):
                continue
            if selected_dir and not name.startswith('.') and suffix in register.RAW:
                expected.append(str(path))
            if suffix in IMPORTABLE and (recursive or not relative_parts):
                candidates.append(str(path))
    expected.sort()
    if not 1 <= len(expected) <= 2000:
        raise Error('Native import requires 1..2000 expected RAW files')
    if not recursive and any(Path(path).parent != folder for path in expected):
        raise Error('Nested expected RAW files require recursive import enabled in native settings')
    return expected, sorted(set(candidates) - set(expected))


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Must be finite and greater than zero')
    return number


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--catalog', required=True, help='Exact absolute path of the already open catalog')
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--i-checked-import-settings', action='store_true')
    p.add_argument('--allow-extra', action='store_true')
    p.add_argument('--ui', action='store_true', help='Human checks dialog and clicks Import')
    p.add_argument('--poll-seconds', type=positive_seconds, default=2)
    p.add_argument('--timeout-seconds', type=positive_seconds, default=1800)
    p.add_argument('--profile', action='store_true')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    return p


def make_adapter(profile):
    manifest = register.ROOT / '.lightroom-runtime/batch/cetacea-batch-runtime.json'
    try:
        if json.loads(manifest.read_text()).get('native_contract') != 1:
            raise ValueError
    except (OSError, ValueError, AttributeError):
        raise Error('Re-prepare a fresh runtime with native_contract=1; see docs/LR_FAST_ADD_RESEARCH.md') from None
    return register.make_adapter(100, profile=profile)


def presence(adapter, paths, folder, check_catalog, *, snapshot=False, clock=time.perf_counter, deadline=None):
    present, folder_paths = set(), None
    for start in range(0, len(paths), 500):
        if deadline is not None and clock() >= deadline:
            raise TimeoutError('Polling deadline reached')
        check_catalog()
        args = {'paths': paths[start:start + 500]}
        if snapshot and start == 0:
            args['folder_path'] = str(folder)
        remaining = deadline - clock() if deadline is not None else None
        if remaining is not None and remaining <= 0:
            raise TimeoutError('Polling deadline reached')
        response = adapter.call_tool('catalog_paths_present', args, **(
            {'timeout_seconds': remaining} if remaining is not None else {}))
        yes, no = response.get('present'), response.get('missing')
        if (response.get('success') is not True or not isinstance(yes, list) or not isinstance(no, list)
                or any(not isinstance(path, str) for path in yes + no)
                or len(set(yes + no)) != len(yes + no) or set(yes + no) != set(args['paths'])):
            raise Error('Invalid exact-path presence response; catalog membership unconfirmed')
        present.update(yes)
        if 'folder_path' in args:
            rows = response.get('folder_paths')
            if (not isinstance(rows, list) or any(not isinstance(path, str)
                    or not Path(path).is_absolute() or '..' in Path(path).parts
                    or not Path(path).is_relative_to(folder) or path == str(folder) for path in rows)):
                raise Error('Invalid folder snapshot response')
            folder_paths = set(rows)
    return present, folder_paths


def checkpoint(stream, report):
    stream.seek(0)
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def run(args, stream, report, *, adapter, guard, prefs_reader, clock, sleep):
    if not Path(args.catalog).is_absolute() or not args.catalog.endswith('.lrcat'):
        raise Error('--catalog must be an absolute .lrcat path')
    folder = Path(report['folder'])
    report['settings'] = prefs_guard(prefs_reader(), args.i_checked_import_settings)
    report['recursive_at_inventory'] = report['settings']['recursive']
    paths, extras = inventory(folder, report['settings']['recursive'])
    report.update(expected_files=paths, total=len(paths), extra_importable_files=extras)
    report['counts'] = dict(present=0, missing=len(paths), existing=0, newly_present=0)
    for path in extras:
        print('EXTRA IMPORTABLE: ' + path)
    checkpoint(stream, report)
    if extras and not args.allow_extra:
        raise Error('Folder-level import would include extra files; inspect list and use --allow-extra explicitly')
    if not args.execute:
        report['status'] = 'DRY_RUN'
        return 0

    def check_catalog():
        record = guard(args.catalog, label='native-trigger-or-readback')
        report['catalog_guard'] = record
        if record.get('matches_expected') is not True:
            raise Error('Open catalog does not exactly match --catalog; stopped')

    check_catalog()  # fail before starting a bridge
    adapter = adapter if adapter is not None else make_adapter(args.profile)
    report['marker'] = 'CETACEA-MOCK' if adapter.testing else 'CETACEA-LIGHTROOM'
    if args.profile:
        adapter.profile = True
        report['profile_events'] = adapter.profile_events
    with adapter._connection():
        before, before_folder = presence(adapter, paths, folder, check_catalog, snapshot=True)
        report['initial_present'] = sorted(before)
        report['initial_extra_catalog_paths'] = sorted(before_folder - set(paths))
        report['counts'].update(existing=len(before), present=len(before), missing=len(paths) - len(before))
        checkpoint(stream, report)
        # Re-read live preferences after pre-snapshot, immediately before the
        # write trigger. No automatic retry, activation, or catalog switching.
        report['settings'] = prefs_guard(prefs_reader(), args.i_checked_import_settings)
        if report['settings']['recursive'] != report['recursive_at_inventory']:
            raise Error('Recursive import setting changed after inventory; rerun')
        check_catalog()
        started = clock()
        report['trigger_started_utc'] = datetime.now(timezone.utc).isoformat()
        report['status'] = 'TRIGGERING'
        checkpoint(stream, report)
        result = adapter.call_tool('native_add_folder_ui' if args.ui else 'native_add_folder',
                                   {'folder_path': str(folder), 'expected_files': paths},
                                   timeout_seconds=args.timeout_seconds)
        if (result.get('success') is not True or result.get('triggered') is not True
                or type(result.get('started_at')) not in (int, float)
                or not math.isfinite(result['started_at'])):
            raise Error('Native trigger acknowledgement invalid; may have triggered, do not blindly retry')
        report['trigger'] = {key: result[key] for key in ('triggered', 'started_at')}
        report['status'] = 'POLLING'
        checkpoint(stream, report)
        if args.ui:
            print('Native dialog requested: human must check Add/settings and click Import; polling now.')
        deadline = started + args.timeout_seconds
        present = before
        while clock() < deadline:
            try:
                present, _ = presence(adapter, paths, folder, check_catalog, clock=clock, deadline=deadline)
            except TimeoutError:
                break
            except Exception:
                if clock() >= deadline:
                    report['poll_reply'] = 'deadline reached; in-flight reply unconfirmed'
                    break
                raise
            report['counts'].update(present=len(present), missing=len(paths) - len(present),
                                    newly_present=len(present - before))
            checkpoint(stream, report)
            if len(present) == len(paths):
                break
            sleep(min(args.poll_seconds, max(0, deadline - clock())))
        report['native_wall_seconds'] = clock() - started
        report['native_wall_scope'] = 'trigger request through last complete polling observation; excludes final folder scan'
        report['missing_paths'] = sorted(set(paths) - present)
        report['status'] = 'COMPLETED' if not report['missing_paths'] else 'TIMEOUT'
        # One final folder snapshot, also on timeout. Catalog membership does
        # not prove LR has finished previews or that no more extras will arrive.
        final_present, final_folder = presence(adapter, paths, folder, check_catalog, snapshot=True)
        report['final_snapshot_present'] = sorted(final_present)
        if report['status'] == 'COMPLETED' and final_present != set(paths):
            report['status'] = 'INCOMPLETE'
        report['counts'].update(present=len(final_present), missing=len(paths) - len(final_present),
                                newly_present=len(final_present - before))
        report['missing_paths'] = sorted(set(paths) - final_present)
        report['extra_catalog_paths'] = sorted(final_folder - set(paths))
        report['extra_adds'] = sorted(final_folder - before_folder - set(paths))
        report['extra_adds_attribution'] = 'observed delta; concurrent import attribution unverified'
        report['native_seconds_per_photo'] = report['native_wall_seconds'] / len(paths)
        report['native_seconds_per_new_photo'] = (
            report['native_wall_seconds'] / len(final_present - before) if final_present - before else None)
        report['completion_scope'] = 'expected path membership only; native engine/previews/extras may still run'
        return 0 if report['status'] == 'COMPLETED' else 1


def main(argv=None, *, adapter=None, guard=None, prefs_reader=None, clock=time.perf_counter, sleep=time.sleep):
    args = parser().parse_args(argv)
    folder, target = register.absolute(args.folder), register.absolute(args.report)
    try:
        if target.is_relative_to(folder):
            raise Error('--report must be outside the input folder')
        register.no_symlink_directory(target.parent)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except (OSError, Error) as exc:
        print(str(exc) if isinstance(exc, Error) else 'Cannot create new report (refuse overwrite)', file=sys.stderr)
        return 1
    report = dict(marker='CETACEA-MOCK' if getattr(adapter, 'testing', False) else 'CETACEA-PLAN',
                  registration_mode='native-ui' if args.ui else 'native', status='PLANNING',
                  catalog=args.catalog, folder=str(folder), total=0, counts={},
                  recursive_at_inventory=None)
    started = clock()
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        try:
            code = run(args, stream, report, adapter=adapter,
                       guard=guard if guard is not None else register.catalog_guard,
                       prefs_reader=prefs_reader if prefs_reader is not None else read_prefs, clock=clock, sleep=sleep)
        except (Exception, KeyboardInterrupt) as exc:
            report['status'] = 'FAILED'
            report['error'] = str(exc) if isinstance(exc, Error) else type(exc).__name__
            report['catalog_state'] = 'unknown; native import may still run if triggered'
            code = 1
        report['wall_seconds'] = clock() - started
        report['seconds_per_photo'] = report['wall_seconds'] / report['total'] if args.execute and report['total'] else None
        checkpoint(stream, report)
    c = report['counts']
    print(f"{report['status']}: expected={report['total']} present={c.get('present', 0)} "
          f"missing={c.get('missing', report['total'])} wall={report['wall_seconds']:.3f}s "
          f"s/photo={report['seconds_per_photo']} extras={len(report.get('extra_adds', []))}")
    if report.get('error'):
        print(report['error'], file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
