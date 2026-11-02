# 功能状态矩阵（Linux 云盒；无密钥/开关全量测试：103 passed，2 skipped（两个真实模型 opt-in 模块）；Phase 2 Mock 阶段：75 passed）

标签：已完成且测试通过 / 已实现但测试失败 / 仅 Mock 验证 / 真实模型小规模验证 / 待 Mac 实机验证 / 尚未开发

2026-11-03 R2 真实 ExFAT SD 目标：**FAIL_STOPPED**。导入发布和预览复用真实 ENOTSUP=45 回退已发生；最终 preview_verify 将 AppleDouble `._*.jpg` 当作 orphan 而失败。产品未修，重复/冲突及真实 Lightroom 测试 NOT_RUN。原有卡内容保留，未清理现场；见 [报告](MACOS_VALIDATION.md) 和 [失败证据](../evidence/mac-r2/failure-analysis.json)。

2026-11-03 R1 Mac 真实 AI 会话：**授权重跑有限样本 PASS**。首次第 2 次请求 TRANSPORT 失败后停止并保留原证据；用户授权重跑并批准具体计划后，真实 DeepSeek + 真实 Lightroom 五阶段完成，核验 OK/mock=false，批准仅一条，RAW/JPG/曝光独立读回通过。累计 driver count=9/13，未重置额度；回归 135 passed、2 skipped。详见 [Mac 报告](MACOS_VALIDATION.md)、[重跑证据](../evidence/mac-r1/retry-1/result.json) 和[首次失败](../evidence/mac-r1/result.json)。未进入 R2。

| # | 功能 | 状态 | 证据 |
|---|---|---|---|
| 5 | 安全导片（扫描、SHA-256、临时文件+读回+硬链接无覆盖提交、最终读回、冲突检测、清单、日志、路径/软链接防护、断点重试、磁盘满/读失败处理） | 已完成且测试通过（Linux ext/overlay 文件系统；Mac 本机及外置 APFS 有有限样本验收；exFAT/SMB 目标待验证） | tests/test_ingest_acceptance.py（场景 1–10） |
| 6 | 任务状态机、审批（绑定 plan_digest，AI 无 approve 权）、幂等、取消/重试/恢复、租约 | 已完成且测试通过 | tests/test_tasks_acceptance.py（场景 11、12、16） |
| 7 | MCP stdio 工具服务（14 个工具仅接受注册 ID，无任意路径/shell/删除/批准；来源列表会返回绝对路径，用户已接受其经 Harness 发给 DeepSeek，见 [数据流](DATA_FLOW.md)） + 人工 CLI 共享同一 SQLite 状态 | 已完成且测试通过（经真实 stdio MCP 客户端及 Harness 实测；Codex/Claude 客户端未实测） | tests/test_mcp.py（场景 15、16 + 共享状态证明） |
| 7b | deepseek-harness MCP 前端（受限工具面） | 保留此前 Linux 真实模型/MOCK Lightroom 记录；另 Mac R1 授权重跑实际 DeepSeek + 真实 Lightroom 单张五阶段通过，仍非可靠性保证；Harness 实验性/未审计 | tests/test_harness_integration.py、tests/test_harness_session_mock.py、evidence/mac-r1/retry-1/、evidence/realmodel/、evidence/fullplan/ |
| 7c | 工具调用 guard：运行前检查及逐轮评估 | 仅 Mock 验证警告和错误路径；真实模型只观察到有工具调用及允许无工具的拒绝 | tests/test_harness_guard.py、tests/test_harness_session_mock.py |
| 7d | 真实模型 opt-in 测试 | 无密钥/开关时两个模块跳过；此前真实 DeepSeek 运行 5 passed，完整计划场景另采样一次 | tests/test_realmodel_gating.py（3 个）、tests/test_realmodel_optin.py、tests/test_realmodel_fullplan_optin.py |
| 7e | 一次审批的五阶段完整流程及恢复 | Mac R1 实际 DeepSeek + 真实 Lightroom 单张完整流程有限通过，一次人工批准；先前合并后真实三照片断连恢复证据仍有效，R1 未另做中断测试 | tests/test_fullplan.py、tests/test_harness_session_mock.py、evidence/mac-r1/retry-1/、evidence/mac-acceptance-merged/、evidence/fullplan/ |
| 8 | Lightroom Mock 适配器（MOCK 标记、真实可解码 JPEG、逐项失败注入） | 仅 Mock 验证 | tests/test_lightroom.py（场景 13） |
| 8b | 真实 Lightroom MCP 适配器（白名单、仅 develop 工具集、on_existing=skip、Linux 默认拒绝） | 已有合并前 Mac 真实 Lightroom 有限样本验收；合并后完整计划待重新验证 | tests/test_lightroom.py::test_real_mcp_interface_only；[Mac 验收](MACOS_VALIDATION.md)、[设备补充](MACOS_DEVICE_VALIDATION.md) |
| 9 | 预览包映射与核验（run-N 不覆盖、存在/解码/尺寸/孤儿/漏图报告、RAW+JPG 配对） | 已完成且测试通过（Mock JPEG 测试；合并前真实 Lightroom 导出有有限样本验收，合并后完整计划待重新验证） | tests/test_lightroom.py（场景 14） |
| – | 端到端 Mock 模拟 + 报告 | 仅 Mock 验证 | scripts/e2e_demo.py → evidence/e2e/ ；tests/test_e2e_script.py |
| 12 | macOS 验收清单 / 回滚 / 安装说明 | 文档已完成；部分条目已有 Mac 有限样本验收 | [交接](MACOS_HANDOFF.md)、[Mac 验收](MACOS_VALIDATION.md)、[设备补充](MACOS_DEVICE_VALIDATION.md) |
| – | Photoshop 适配、AI 选片/调色、Windows | 尚未开发 | – |
| – | 真实 Lightroom Classic、macOS、Apple Silicon、真实卡片/读卡器、Mac 上 Harness 联调 | 合并前 Mac、真实 Lightroom 和实体卡已有有限样本验收；合并后完整计划及 Mac 上 Harness 联调待验证 | [Mac 验收](MACOS_VALIDATION.md)、[设备补充](MACOS_DEVICE_VALIDATION.md) |

## 16 个必需场景 → 测试对应
1 test_01_normal；2 test_02_subdirs；3 test_03_photographers；4 test_04_identity；5 test_05_existing_correct；6 test_06_existing_conflict；7 test_07_interrupt；8 test_08_space / test_08_mid_write；9 test_09_read_error；10 test_10_paths；11 test_11_idempotency_and_concurrency；12 test_12_cancel_retry；13 test_13_partial_failure；14 test_14_preview_mismatch_and_new_run；15 test_15_shared_state_idempotent_mcp；16 test_16_permissions + test_16_mcp_denials。

MCP stdio 测试在 Codex 沙箱外通过；此前未验证的记录仅反映 Codex 沙箱限制。合并前记录：当时 `mac-validation` 分支尚未合并，本阶段源文件仅涉及 `core.py` 和 `mcp_server.py`，合并时需核对。合并后的完整计划仍待 Mac 重新验证。

[Mac 实机路线图](ROADMAP.md)。
