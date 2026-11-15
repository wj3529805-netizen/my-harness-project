# CETACEA AI Photo Workbench（鲸目 AI 摄影工作台）— Phase 1 + Phase 2（Harness 接入，实验性）

安全导片 → 任务/审批 → Lightroom（Mock / 经 lightroom-mcp 的真实适配器）→ 预览包核验；人工 CLI 与 AI（stdio MCP）共享同一份 SQLite 状态。

> Linux 上的所有 Lightroom 结果均为 **MOCK**，不代表 macOS 或真实 Lightroom 已测试。见 `docs/STATUS.md`、`docs/KNOWN_RISKS.md`、`docs/MACOS_HANDOFF.md`。

## 安装与测试（项目内 venv，无需系统级安装；需 Python ≥ 3.12）
```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m pytest -q          # 已测：103 passed，2 skipped（Linux，无密钥/开关；两个真实模型 opt-in 模块跳过，需具备 Harness 测试依赖）
.venv/bin/python scripts/e2e_demo.py   # 端到端 Mock，输出 evidence/e2e/
```
## 人工流程示例
```bash
H=/tmp/cetacea-home
cetacea init --home $H --library /tmp/lib --preview /tmp/prev
cetacea --home $H source add card /path/to/CARD_COPY      # 源只读
cetacea --home $H order create order1 "婚纱订单"
cetacea --home $H photographer add p1 "摄影师A"
cetacea --home $H preset add base "鲸目基础预设"
cetacea --home $H plan order1 p1 card --preset-id base --stages ingest lr_register lr_preset lr_export preview_verify --json
cetacea --home $H approve TASK_ID PLAN_DIGEST              # 只有人类可以批准
cetacea --home $H execute TASK_ID && cetacea --home $H report TASK_ID
```
## AI 客户端接入（stdio MCP）
`cetacea --home $H mcp-serve`（AI 主体：read/plan/execute/cancel/lightroom；永远没有 approve/admin）。工具只接受 ID，14 个工具均有描述。MCP 的 `photo_plan_import` 省略 `stages` 且提供 `preset_id` 时生成五阶段完整计划，经一次人工批准后由 `photo_execute_import` 端到端执行；仅导片须显式传 `stages=["ingest"]`。详情见 [完整计划流程](docs/FULLPLAN.md)。配置片段见 `bash scripts/mac/print_lightroom_mcp_config.sh`（只打印）。
## Harness 前端（Phase 2，实验性）
`deepseek-harness`（固定提交，MIT）经其 MCP 客户端插件以 stdio 调用 CETACEA，工具名 `mcp__cetacea__*`。**必须同时应用 `harness/cetacea-restricted.patch.yml`**（关闭 Harness 自带 bash/文件/web 工具）。准备与用法见 `harness/README.md`。**已用真实 DeepSeek 小规模验证（此前 5 个场景各 1 次、17 次请求；完整计划另 1 次、8 次请求）；非可靠性保证；仅 Linux；Harness 仍为实验性/未审计**。真实 Lightroom 和 macOS 尚未测试。
## 文档
仓库源代码采用 [MIT 许可证](LICENSE)；许可范围见 [NOTICE](NOTICE)；样片独立适用 [samples/LICENSE.txt](samples/LICENSE.txt)。
[Mac 实机路线图](docs/ROADMAP.md)。
`docs/SPEC.md` 规格；`docs/REUSE_DECISION.md` 复用决策；`docs/ARCHITECTURE.md` 目录结构；`docs/THIRD_PARTY.md` 依赖/许可证/固定提交；`docs/STATUS.md` 状态矩阵；`docs/MACOS_HANDOFF.md` Mac 交接；[docs/KNOWN_RISKS.md](docs/KNOWN_RISKS.md) 风险；[docs/DATA_FLOW.md](docs/DATA_FLOW.md) 工具结果的数据流；[docs/FULLPLAN.md](docs/FULLPLAN.md) 完整计划与审批。

## 按拍摄日期分单 / Filter by capture date and time

同一来源可按每天生成独立计划，先筛选再哈希；来源目录始终只读。
One card can produce separate daily plans; only matching files are hashed.
以下为使用示例（不是自动执行命令）：

```bash
cetacea --home H source add card_z6 "/Volumes/NIKON Z6_3 /DCIM"
cetacea --home H scan card_z6 --date 2026-11-14
cetacea --home H plan ORDER_DAY1 PHOTOG card_z6 --date 2026-11-14 --stages ingest
cetacea --home H plan ORDER_DAY2 PHOTOG card_z6 --date 2026-11-15 --stages ingest
# 来源默认筛选；plan/scan 显式传条件时整体替换默认条件。
cetacea --home H source add day1 /path/to/CARD_COPY --date 2026-11-14
# 可重复日期；日期与时间范围取交集。from 包含，to 不包含。
cetacea --home H scan card_z6 --date 2026-11-14 --date 2026-11-15
cetacea --home H plan ORDER PHOTOG card_z6 --from 2026-11-14T18:00:00 --to 2026-11-15 --tz Asia/Shanghai --stages ingest
```

每个 `--date` 表示本地 `[00:00, 次日00:00)`；`--from`/`--to` 接受 ISO
日期时间或 `YYYY-MM-DD`（午夜）。默认时区为 config.json 的
`capture_timezone: "Asia/Shanghai"`，CLI 的 `--tz` 可覆盖。
Dates are local calendar days; date lists and the half-open time range are ANDed.
Explicit filters replace the source default. EXIF priority is DateTimeOriginal,
then DateTimeDigitized only if Original is absent, then IFD0 DateTime only if both
are absent. OffsetTimeOriginal is converted to the configured timezone. Naive
camera times are assumed local. Unreadable EXIF uses a same-directory/same-stem
photo's EXIF time for companions, otherwise file mtime (which may reflect copying).

`scan` 返回同样的 `capture_filter` 汇总：匹配/排除数量、按相对父目录计数、
时间来源、首末拍摄时间，以及匹配和排除文件合计最多 50 条 mtime 回退路径。
`plan` 的匹配项含 `capture_time`、`capture_time_source`；排除文件只记计数
（mtime 人工复核清单除外）。零匹配的 scan 可预览，零匹配的 plan 报错。
无筛选时保留原有计划 JSON 和摘要。详见 [CLI/MCP 日期筛选](docs/CAPTURE_FILTER.md)。

MCP（仅登记 ID，无时区或路径参数 / registered IDs only, config timezone）：

```python
photo_scan_source(source_id="card_z6", dates=["2026-11-14"])
photo_plan_import(order_id="ORDER_DAY1", photographer_id="PHOTOG", source_id="card_z6",
                  dates=["2026-11-14"], stages=["ingest"])
photo_plan_import(order_id="ORDER", photographer_id="PHOTOG", source_id="card_z6",
                  time_from="2026-11-14T18:00:00", time_to="2026-11-15", stages=["ingest"])
```
