#!/usr/bin/env python3
"""Register imported photographs in place; dry-run unless --execute is given."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cetacea.lightroom import RealLightroomMcpAdapter, VerifiedFile
from r6_lightroom import catalog_guard


RAW = frozenset('3fr ari arw bay cap cr2 cr3 crw dcr dcs dng drf eip erf fff gpr iiq '
                'k25 kdc mdc mef mos mrw nef nrw orf ori pef ptx pxn raf raw rw2 rwl '
                'sr2 srf srw x3f'.split())
JPG = frozenset(('jpg', 'jpeg', 'jpe'))
EXCLUDED = frozenset(('proof', 'proofs', 'preview', 'previews', '预览', '预览图', '预览照片'))


class RegistrationError(ValueError):
    """An actionable, safe-to-print operator error without bridge payloads."""


def batch_size(value):
    try:
        number = int(value)
        if not 1 <= number <= 200:
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError('batch-size 必须为 1–200 的整数') from None


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder', type=Path, action='append', required=True,
                   help='已完成导入的项目目录；可重复，递归扫描且不跟随符号链接')
    p.add_argument('--catalog', required=True, help='期望已打开的 .lrcat 绝对路径')
    p.add_argument('--include', choices=('raw', 'jpg', 'all'), default='raw')
    p.add_argument('--exclude-dir', action='append', default=[], help='追加排除的目录名（不区分大小写）')
    p.add_argument('--batch-size', type=batch_size, default=100)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='只生成计划（默认），不连接 Lightroom')
    mode.add_argument('--execute', action='store_true', help='执行只添加登记')
    p.add_argument('--report', type=Path, required=True, help='新建本地 JSON 报告；拒绝覆盖、须在照片目录外')
    return p


def absolute(path):
    # Normalize lexical . and .. without resolving symlinks to another input.
    return Path(os.path.abspath(path.expanduser()))


def no_symlink_directory(path):
    for part in (*reversed(path.parents), path):
        mode = part.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise RegistrationError('目录或其父路径不是普通目录（拒绝符号链接）')


def collect(folders, include, excluded):
    extensions = RAW if include == 'raw' else JPG if include == 'jpg' else RAW | JPG
    found = {}
    def walk_error(error):
        raise error
    for folder in folders:
        no_symlink_directory(folder)
        if folder.name.casefold() in excluded:
            continue
        for directory, dirs, names in os.walk(folder, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(name for name in dirs if name.casefold() not in excluded
                             and not (Path(directory) / name).is_symlink())
            for name in sorted(names):
                if name.startswith('.') or Path(name).suffix.lower().lstrip('.') not in extensions:
                    continue
                path = Path(directory) / name
                info = path.lstat()
                if stat.S_ISREG(info.st_mode):
                    found[str(path)] = info.st_size
    # The adapter's carrier type is VerifiedFile, but this entry point does not
    # claim byte verification or repeat the importer's copy/hash checks. Empty
    # sha256 is intentional: only exact-path catalog membership is read back.
    return [VerifiedFile(hashlib.sha256(path.encode()).hexdigest(), Path(path), '', size)
            for path, size in sorted(found.items())]


def make_adapter(size):
    runtime = ROOT / '.lightroom-runtime/batch'
    index = runtime / 'node_modules/@mskalski/lightroom-mcp/dist/index.js'
    hint = ('缺少或无效的批量补丁桥；请先运行 scripts/mac/prepare_lightroom_batch.py '
            '并在安排好的时段手动启用配套插件（见 docs/LIGHTROOM_BATCH.md）')
    try:
        manifest = json.loads((runtime / 'cetacea-batch-runtime.json').read_text())
        if (manifest.get('tool') != 'import_photos_batch'
                or manifest.get('upstream') != '@mskalski/lightroom-mcp@0.26.0'
                or manifest.get('max_batch_size') != 200 or not index.is_file()):
            raise ValueError
    except (OSError, ValueError, AttributeError):
        raise RegistrationError(hint) from None
    node = shutil.which('node')
    if not node:
        raise RegistrationError('找不到本地 node；请先将 Node 加入 PATH')
    # Stop on lost transport/reply. A new invocation consults the catalog again;
    # never activate, restart, or switch Lightroom, and never download via npx.
    return RealLightroomMcpAdapter(command=[node, str(index)], batch_size=size,
                                   backoff_schedule=[], activate_hook=None)


def counts():
    return dict(added=0, existing=0, failed=0, pending=0)


def checkpoint(stream, report):
    report['counts'] = counts()
    for batch in report['batches']:
        for key, value in batch['counts'].items():
            report['counts'][key] += value
    stream.seek(0)
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def run(args, stream, report, *, adapter=None, guard=None):
    if not Path(args.catalog).is_absolute() or not args.catalog.endswith('.lrcat'):
        raise RegistrationError('--catalog 必须是 .lrcat 绝对路径')
    if any(not name or name in ('.', '..') or '/' in name for name in args.exclude_dir):
        raise RegistrationError('--exclude-dir 必须是单个目录名，可重复使用')
    excluded = EXCLUDED | {name.casefold() for name in args.exclude_dir}
    files = collect([Path(folder) for folder in report['folders']], args.include, excluded)
    report['total'] = len(files)
    report['excluded_dirs'] = sorted(excluded)
    for start in range(0, len(files), args.batch_size):
        paths = [str(f.abs_path) for f in files[start:start + args.batch_size]]
        report['batches'].append(dict(index=len(report['batches']) + 1, size=len(paths),
                                      status='planned' if not args.execute else 'not_attempted',
                                      counts={**counts(), 'pending': len(paths)}, paths=paths))
    checkpoint(stream, report)
    if not args.execute:
        report['status'] = 'DRY_RUN'
        return 0
    adapter = adapter if adapter is not None else make_adapter(args.batch_size)
    report['marker'] = 'CETACEA-MOCK' if adapter.testing else 'CETACEA-LIGHTROOM'
    if not files:
        report['status'] = 'COMPLETED'
        return 0
    guard = guard if guard is not None else catalog_guard
    for batch in report['batches']:
        def check_catalog():
            record = guard(args.catalog, label=f"daily-batch-{batch['index']}")
            batch['catalog_guard'] = record
            if record.get('matches_expected') is not True:
                batch['safe_error'] = 'Lightroom 未只打开 --catalog 指定的 catalog；当前批未写入，已停止后续批次'
                raise RegistrationError(batch['safe_error'])
        group = files[(batch['index'] - 1) * args.batch_size:batch['index'] * args.batch_size]
        batch['status'] = 'running'
        report['status'] = 'RUNNING'
        checkpoint(stream, report)
        # Outer batches provide durable progress and fail-fast behavior; the
        # adapter still runs its safety callback immediately before each write.
        results = adapter.register(group, before_batch=check_catalog)
        batch['counts'] = counts()
        rows = []
        for i, file in enumerate(group):
            result = results[i] if i < len(results) else None
            good = (result is not None and result.asset_id == file.asset_id and not result.error
                    and result.status in ('added', 'existing')
                    and result.photo_id == str(file.abs_path))
            status = result.status if good else 'failed'
            batch['counts'][status] += 1
            # Never copy arbitrary plug-in errors into stdout or the report:
            # bridge payloads can contain credentials and private identifiers.
            rows.append({'path': str(file.abs_path), 'status': status})
        batch['results'] = rows
        batch['status'] = 'incomplete' if batch['counts']['failed'] else 'completed'
        if batch['counts']['failed'] or len(results) != len(group):
            batch['status'] = 'incomplete'
            batch['catalog_state'] = 'unknown_for_failed_paths'
            report['status'] = 'INCOMPLETE'
            report['error'] = batch.get('safe_error') or (
                '当前批未确认完成，可能已部分写入；停止后续批次。'
                '确认 Lightroom 和补丁插件恢复后，换一个报告文件重跑同一命令即可续登记。'
                '若缺少批量 API，请先运行 scripts/mac/prepare_lightroom_batch.py。')
            checkpoint(stream, report)
            return 1
        checkpoint(stream, report)
    report['status'] = 'COMPLETED'
    return 0


def main(argv=None, *, adapter=None, guard=None):
    args = parser().parse_args(argv)
    folders = list(dict.fromkeys(absolute(path) for path in args.folder))
    target = absolute(args.report)
    try:
        # Refuse writing even inside an excluded input subdirectory. No source
        # directory is ever created, modified, renamed or removed by this CLI.
        if any(target.is_relative_to(folder) for folder in folders):
            raise RegistrationError('--report 必须位于所有 --folder 目录之外')
        no_symlink_directory(target.parent)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        print('报告文件已存在；请换一个 --report 路径，原文件未改动。', file=sys.stderr)
        return 1
    except (OSError, RegistrationError) as exc:
        print(str(exc) if isinstance(exc, RegistrationError) else f'无法新建报告：{type(exc).__name__}',
              file=sys.stderr)
        return 1
    report = dict(marker='CETACEA-MOCK' if getattr(adapter, 'testing', False) else 'CETACEA-PLAN',
                  status='PLANNING', mode='execute' if args.execute else 'dry-run',
                  catalog=args.catalog, folders=[str(folder) for folder in folders],
                  include=args.include, batch_size=args.batch_size, total=0, counts=counts(), batches=[])
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        try:
            code = run(args, stream, report, adapter=adapter, guard=guard)
        except (Exception, KeyboardInterrupt) as exc:
            report['status'] = 'FAILED'
            report['error'] = str(exc) if isinstance(exc, RegistrationError) else type(exc).__name__
            for batch in report['batches']:
                if batch['status'] == 'running':
                    batch['status'] = 'incomplete'
                    batch['counts'] = {**counts(), 'failed': batch['size']}
                    batch['catalog_state'] = 'unknown_for_failed_paths'
            code = 1
        checkpoint(stream, report)
    c = report['counts']
    print(f"{'演练' if not args.execute else '登记'} {report['status']}：共 {report['total']} 张，"
          f"新增 {c['added']}，已有 {c['existing']}，未确认/失败 {c['failed']}，待处理 {c['pending']}。")
    if report.get('error'):
        print(report['error'], file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
