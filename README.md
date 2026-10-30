# CETACEA AI Photo Workbench（鲸目 AI 摄影工作台）— Phase 1

安全导片 → 任务/审批 → Lightroom（Mock / 经 lightroom-mcp 的真实适配器）→ 预览包核验；人工 CLI 与 AI（stdio MCP）共享同一份 SQLite 状态。

> Linux 上的所有 Lightroom 结果均为 **MOCK**，不代表 macOS 或真实 Lightroom 已测试。见 `docs/STATUS.md`、`docs/KNOWN_RISKS.md`、`docs/MACOS_HANDOFF.md`。

## 安装与测试（项目内 venv，无需系统级安装；需 Python ≥ 3.12）
```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m pytest -q          # 期望：71 passed
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
`cetacea --home $H mcp-serve`（AI 主体：read/plan/execute/cancel/lightroom；永远没有 approve/admin）。工具只接受 ID。配置片段见 `bash scripts/mac/print_lightroom_mcp_config.sh`（只打印）。
## 文档
`docs/SPEC.md` 规格；`docs/REUSE_DECISION.md` 复用决策；`docs/ARCHITECTURE.md` 目录结构；`docs/THIRD_PARTY.md` 依赖/许可证/固定提交；`docs/STATUS.md` 状态矩阵；`docs/MACOS_HANDOFF.md` Mac 交接；`docs/KNOWN_RISKS.md` 风险。
