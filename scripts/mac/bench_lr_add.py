#!/usr/bin/env python3
"""TEST-catalog-only benchmark wrapper; dry-run unless --execute is given."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import register_import_to_lr as register
import lr_native_add as native


def test_catalog(value):
    """Inspect path components only; never open or stat a .lrcat file.

    Refuse symlinked ancestors, avoiding aliases into the production tree.
    Comparison is case-insensitive for the usual macOS filesystem.
    """
    raw = Path(value).expanduser()
    if not raw.is_absolute() or raw.suffix.lower() != '.lrcat':
        raise argparse.ArgumentTypeError('catalog must be an absolute TEST .lrcat path')
    path = Path(os.path.abspath(raw))
    protected = Path.home() / 'Pictures' / 'Lightroom'
    def below(candidate):
        return candidate.casefold() == str(protected).casefold() or candidate.casefold().startswith(str(protected).casefold() + '/')
    # Reject lexically before inspecting any protected parent.
    if below(str(path)) or below(str(raw)):
        raise argparse.ArgumentTypeError('production Lightroom catalog directory is forbidden')
    for parent in reversed(path.parents):
        if parent.is_symlink():
            raise argparse.ArgumentTypeError('catalog ancestors must not be symlinks')
    # lstat only: reject a leaf alias without opening any catalog contents.
    if path.is_symlink():
        raise argparse.ArgumentTypeError('catalog path must not be a symlink')
    return str(path)


def main(argv=None, *, adapter=None, guard=None, prefs_reader=None, clock=None, sleep=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog', required=True, type=test_catalog)
    p.add_argument('--folder', required=True, type=Path, action='append')
    p.add_argument('--mode', choices=('baseline', 'fast', 'native'), required=True)
    p.add_argument('--batch-size', type=register.batch_size, default=100)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--profile', action='store_true')
    p.add_argument('--ui', action='store_true')
    p.add_argument('--i-checked-import-settings', action='store_true')
    p.add_argument('--allow-extra', action='store_true')
    p.add_argument('--poll-seconds', type=native.positive_seconds, default=2)
    p.add_argument('--timeout-seconds', type=native.positive_seconds, default=1800)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    if args.mode == 'native':
        if len(args.folder) != 1:
            p.error('native mode requires exactly one --folder per run')
        opts = ['--catalog', args.catalog, '--folder', str(args.folder[0]), '--report', str(args.report),
                '--poll-seconds', str(args.poll_seconds), '--timeout-seconds', str(args.timeout_seconds),
                '--execute' if args.execute else '--dry-run']
        for flag in ('ui', 'i_checked_import_settings', 'allow_extra', 'profile'):
            if getattr(args, flag):
                opts += ['--' + flag.replace('_', '-')]
        timing = {key: value for key, value in dict(clock=clock, sleep=sleep).items() if value is not None}
        return native.main(opts, adapter=adapter, guard=guard, prefs_reader=prefs_reader, **timing)
    if args.ui or args.allow_extra or args.i_checked_import_settings:
        p.error('--ui / --allow-extra / --i-checked-import-settings require --mode native')
    opts = ['--catalog', args.catalog, '--report', str(args.report), '--batch-size', str(args.batch_size)]
    for folder in args.folder:
        opts += ['--folder', str(folder)]
    opts += ['--execute' if args.execute else '--dry-run']
    if args.mode == 'fast':
        opts += ['--fast']
    if args.profile:
        opts += ['--profile']
    # register performs catalog_guard before EACH write and fast final readback;
    # no launch, catalog switching, dialog automation, or direct catalog I/O.
    return register.main(opts, adapter=adapter, guard=guard)


if __name__ == '__main__':
    raise SystemExit(main())
