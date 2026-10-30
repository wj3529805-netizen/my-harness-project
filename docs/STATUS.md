# 功能状态矩阵（Linux 云盒，2026-10-30；全量测试：71 passed）

标签：已完成且测试通过 / 已实现但测试失败 / 仅 Mock 验证 / 待 Mac 实机验证 / 尚未开发

| # | 功能 | 状态 | 证据 |
|---|---|---|---|
| 5 | 安全导片（扫描、SHA-256、临时文件+读回+硬链接无覆盖提交、最终读回、冲突检测、清单、日志、路径/软链接防护、断点重试、磁盘满/读失败处理） | 已完成且测试通过（Linux ext/overlay 文件系统；APFS/exFAT/SMB 待 Mac 验证） | tests/test_ingest_acceptance.py（场景 1–10） |
| 6 | 任务状态机、审批（绑定 plan_digest，AI 无 approve 权）、幂等、取消/重试/恢复、租约 | 已完成且测试通过 | tests/test_tasks_acceptance.py（场景 11、12、16） |
| 7 | MCP stdio 工具服务（14 个仅 ID 的工具，无路径/shell/删除/批准） + 人工 CLI 共享同一 SQLite 状态 | 已完成且测试通过（经真实 stdio MCP 客户端子进程；**未用真实 Harness/Codex/Claude 客户端实测**） | tests/test_mcp.py（场景 15、16 + 共享状态证明） |
| 7b | deepseek-harness 接入 | 尚未开发（仅文档中的配置片段，未实测；盒子 Node 20 < 24.9） | scripts/mac/print_lightroom_mcp_config.sh |
| 8 | Lightroom Mock 适配器（MOCK 标记、真实可解码 JPEG、逐项失败注入） | 仅 Mock 验证 | tests/test_lightroom.py（场景 13） |
| 8b | 真实 Lightroom MCP 适配器（白名单、仅 develop 工具集、on_existing=skip、Linux 默认拒绝） | 仅接口级验证（对假 MCP stdio 服务器）→ **待 Mac 实机验证** | tests/test_lightroom.py::test_real_mcp_interface_only |
| 9 | 预览包映射与核验（run-N 不覆盖、存在/解码/尺寸/孤儿/漏图报告、RAW+JPG 配对） | 已完成且测试通过（仅针对 Mock JPEG；真实 Lightroom 导出待 Mac 验证） | tests/test_lightroom.py（场景 14） |
| – | 端到端 Mock 模拟 + 报告 | 仅 Mock 验证 | scripts/e2e_demo.py → evidence/e2e/ ；tests/test_e2e_script.py |
| 12 | macOS 验收清单 / 回滚 / 安装说明 | 文档已完成；所有条目 **待 Mac 实机验证** | docs/MACOS_HANDOFF.md |
| – | Photoshop 适配、AI 选片/调色、Windows | 尚未开发 | – |
| – | 真实 Lightroom Classic、macOS、Apple Silicon、真实卡片/读卡器、真实 Harness 联调 | 待 Mac 实机验证（未执行） | – |

## 16 个必需场景 → 测试对应
1 test_01_normal；2 test_02_subdirs；3 test_03_photographers；4 test_04_identity；5 test_05_existing_correct；6 test_06_existing_conflict；7 test_07_interrupt；8 test_08_space / test_08_mid_write；9 test_09_read_error；10 test_10_paths；11 test_11_idempotency_and_concurrency；12 test_12_cancel_retry；13 test_13_partial_failure；14 test_14_preview_mismatch_and_new_run；15 test_15_shared_state_idempotent_mcp；16 test_16_permissions + test_16_mcp_denials。
