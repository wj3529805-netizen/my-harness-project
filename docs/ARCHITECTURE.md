# 项目目录结构与模块说明

```
cetacea-workbench/
├── AGENTS.md                    # 给编码代理的硬规则
├── pyproject.toml               # 包 cetacea，控制台脚本 `cetacea`
├── src/cetacea/
│   ├── config.py db.py audit.py # 配置/已登记资源、SQLite(WAL)、审计日志
│   ├── perms.py                 # Principal（human / ai），scope 权限；AI 永远没有 approve/admin
│   ├── tasks.py                 # 任务状态机与合法转移表
│   ├── core.py                  # Workbench 服务：计划/批准/执行/取消/重试/恢复，Lightroom 阶段
│   ├── ingest/                  # pathsafe（路径防护）、scanner、copier（临时文件+读回+硬链接原子提交）、manifest
│   ├── lightroom/               # base（ABC）、mock（MOCK，明确标记）、real_mcp（lightroom-mcp 白名单适配器）
│   ├── preview.py report.py     # 预览包 run-N、映射与核验、报告
│   ├── mcp_server.py            # stdio MCP 服务（AI 入口，仅受控 ID，无路径/shell/删除/批准）
│   └── cli.py                   # 人工入口（与 MCP 共享同一份 SQLite 状态）
├── tests/                       # 自动化测试（16 个必需场景 + 额外安全测试）
├── scripts/e2e_demo.py          # 端到端 Mock 演示，输出 evidence/e2e/
├── scripts/mac/                 # macOS 只读检查与配置打印脚本（不安装、不写入）
├── docs/                        # SPEC / REUSE_DECISION / THIRD_PARTY / MACOS_HANDOFF / STATUS / KNOWN_RISKS
└── evidence/e2e/                # 端到端 Mock 运行证据
```
数据流：CLI（human）与 MCP（ai）都构造同一个 `Workbench(home)`，状态都落在 `<home>/state.sqlite3`；批准只能由 human principal 写入 `approvals`，且绑定 `plan_digest`。
