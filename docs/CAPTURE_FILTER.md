# 拍摄日期与时间筛选 / Capture filtering

`source add`、`scan`、`plan` 都接受 `--date YYYY-MM-DD`（可重复）、
`--from ISO`、`--to ISO` 和 `--tz ZONE`。`source list` 显示来源保存的
`capture_filter`。来源的默认条件适用于 scan 和 plan；显式日期或范围条件
整体覆盖默认条件，单独 `--tz` 则调整默认条件的本地时区。

```bash
cetacea --home H source add day1 /path/to/CARD_COPY --date 2026-11-14
cetacea --home H scan day1
cetacea --home H plan ORDER_DAY2 PHOTOG day1 --date 2026-11-15 --stages ingest
cetacea --home H scan day1 --from 2026-11-14T12:00:00+08:00 --to 2026-11-15
```

Dates use local `[midnight, next midnight)` intervals. Repeatable dates form a
union; date and time constraints combine with AND. `from` is inclusive and `to`
is exclusive. Bare dates mean local midnight. Invalid formats, unknown timezones,
and `from >= to` raise ValueError (MCP `INVALID_ARGUMENT`).

config.json 的 `capture_timezone` 默认 `Asia/Shanghai`。相机无偏移的 EXIF
按该本地时区解释，mtime 时间戳转换到该时区；有 OffsetTimeOriginal 的 EXIF
先按偏移解释，再转换。CLI `--tz` 可覆盖；MCP 不提供 tz 参数。
Core `add_source`、`scan_source`、`plan_import` 接受 `capture_filter=None` 和
可选 `tz`；例如 `capture_filter={"date": ["2026-11-14"]}`。
Core 的空字典 `{}` 可显式取消来源默认条件；None 使用来源默认条件。

MCP signatures (only registered identifiers, no filesystem inputs):

```python
photo_scan_source(source_id, dates=None, time_from=None, time_to=None)
photo_plan_import(order_id, photographer_id, source_id,
                  batch_label=None, preset_id=None, stages=None,
                  dates=None, time_from=None, time_to=None)
photo_scan_source(source_id="card_z6", dates=["2026-11-14"])
photo_plan_import(order_id="ORDER", photographer_id="PHOTOG", source_id="card_z6",
                  dates=["2026-11-14"], time_from="2026-11-14T12:00:00",
                  time_to="2026-11-15", stages=["ingest"])
```

The reader supports classic TIFF-based RAW (including practical RW2/ORF header
variants) and JPEG APP1 EXIF, with no new dependencies. Priority: ExifIFD
DateTimeOriginal 0x9003; DateTimeDigitized 0x9004 only when Original is absent;
IFD0 DateTime 0x0132 only when both are absent. Invalid higher-priority tags cause
mtime/companion fallback rather than selecting a lower-priority tag. At most
1 MiB is read per file, with bounded IFD counts, no cyclic pointer traversal,
read-only/no-follow opens and no source writes. Subseconds are currently ignored.

先读取拍摄时间再筛选，只对匹配文件计算 SHA-256；扫描摘要只含匹配文件的
原有 `(rel_path, size, sha256)` 三元组。不同条件即使选中相同文件，规范化的
spec 仍计入幂等键和计划摘要。无过滤条件时，计划无新增字段且摘要算法不变。

Filtered scan reports and plans include `capture_filter`:

- `spec`: normalized `date` list (sorted, unique), ISO `from` / `to` with offsets,
  and `tz`; absent constraints are omitted.
- `matched`, `filtered_out`, `time_source_counts` (matched exif/companion/mtime),
  `mtime_fallback_matched`, `mtime_fallback_filtered_out`.
- `matched_by_folder`, `filtered_out_by_folder`: relative parent directories,
  e.g. `DCIM/143NZ6_3` (`.` for files at the source root).
- `mtime_fallback_files`: `matched` and `filtered_out` relative-path lists,
  with **at most 50 paths total**, in deterministic traversal order.
- `first_capture`, `last_capture`: matched extrema as ISO timestamps with offsets;
  null for an empty scan. Plans reject zero matches.

每个匹配文件有 `capture_time` 和 `capture_time_source`。无 EXIF 的同目录、
同文件名主干的文件继承照片（RAW/JPEG）的 EXIF 时间，标为 companion；同主干
RAW/JPEG 都有 EXIF 时按扫描文件名排序选择第一个。其余用 mtime。排除文件无
逐项清单，仅保留汇总和上述有界 mtime 复核清单。scan 会读取/哈希匹配文件，
但不会创建导入任务；plan 仍需按原流程由人批准才能执行。
