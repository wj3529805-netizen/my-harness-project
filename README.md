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
[Mac 实机路线图](docs/ROADMAP.md)。
`docs/SPEC.md` 规格；`docs/REUSE_DECISION.md` 复用决策；`docs/ARCHITECTURE.md` 目录结构；`docs/THIRD_PARTY.md` 依赖/许可证/固定提交；`docs/STATUS.md` 状态矩阵；`docs/MACOS_HANDOFF.md` Mac 交接；[docs/KNOWN_RISKS.md](docs/KNOWN_RISKS.md) 风险；[docs/DATA_FLOW.md](docs/DATA_FLOW.md) 工具结果的数据流；[docs/FULLPLAN.md](docs/FULLPLAN.md) 完整计划与审批。
