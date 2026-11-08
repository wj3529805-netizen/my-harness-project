# 功能状态矩阵（Linux 云盒；无密钥/开关全量测试：103 passed，2 skipped（两个真实模型 opt-in 模块）；Phase 2 Mock 阶段：75 passed）

R5 已在 `prep/R5` 完成样片替换和当前树脱敏；所有者已确定样片许可及标识保留决定；范围、限制及待决事项见 [最终验收](FINAL_ACCEPTANCE.md)。

标签：已完成且测试通过 / 已实现但测试失败 / 仅 Mock 验证 / 真实模型小规模验证 / 待 Mac 实机验证 / 尚未开发

2026-11-06 代码许可：仓库源代码采用 MIT，已添加根目录 [LICENSE](../LICENSE)；样片仍适用独立的 [samples/LICENSE.txt](../samples/LICENSE.txt)。本次许可与文档更新后运行 `.venv/bin/python -m pytest -q`：**303 passed、2 skipped**（真实模型 opt-in 未启用）。

2026-11-07 纯 NEF、纯 JPG、混合拷入：核心拷贝逻辑未改，只加合成字节回归和规则说明。当时本环境 `.venv/bin/python -m pytest -q` 为 **295 passed、4 skipped**。与 2026-11-06 的 303 之差是新增 5 个测试，以及两个 harness 模块因未安装 `third_party-review/deepseek-harness` 在收集前跳过（模块内 13 个测试未执行）；两个真实模型 opt-in 模块仍因无密钥跳过。

2026-11-07 Harness `lightroom_get_status`：`run_session.sh` 把子进程 `HOME` 换成临时目录，Lightroom 桥用 `os.homedir()` 找 token；CLI 继承操作者 `HOME`，所以同一 `real_mcp` 配置下 CLI 已连接、Harness 探针失败。失败文字 “Lightroom owns the ports… MIDI2LR” 来自 lightroom-mcp `55cd17f` 的 `STALE_LISTENER_MESSAGE`，是探针没得到应答后的端口诊断。修复只把启动脚本时的操作者家目录作为 `CETACEA_BRIDGE_HOME` 传给桥子进程的 `HOME`，不读、不复制 token。批准写入 `approvals` 后任务仍保持 `WAITING_APPROVAL`、`run_count` 0，直到 `execute`。本环境随后 `.venv/bin/python -m pytest -q` 为 **304 passed、4 skipped**，无失败。跳过仍是未安装的两个 harness 模块（13 个测试未执行）和两个无密钥的真实模型模块；这次读了固定提交 `ce7073d` 的 MCP 客户端源码，但没有把跳过的集成测试当成已通过。Linux 测试不能代替 Mac 上的桥复测。

2026-11-08 本机导入界面：同一分支增加只监听 127.0.0.1 的中文拷入页，复用 plan/approve/execute，仅 ingest，不调用模型或 Lightroom。本环境 `.venv/bin/python -m pytest -q` 为 **313 passed、4 skipped**，无失败；跳过项与上一次相同。Mac 双击启动器尚未在 Mac 上验收，这次 Linux 结果不能代替那一次真机界面验收。

2026-11-06 other-card/USB reader：**PASS**（有界 R3，12 NEF）。证据 `evidence/mac-r3/run-other-card-20261106-005829/`；`source_protocol=USB`；与内置 SD 同名卷靠 UUID 区分；未拔 Studio。回归 303 passed、2 skipped。见 [说明](../evidence/mac-r3/NOTES-other-card-20261106.md)。

2026-11-03 R2 真实 ExFAT SD 目标：**PASS_IN_SCOPE（单样本）**。原始 `2a8d669` / `evidence/mac-r2/` 因 `preview.verify` 把 AppleDouble `._*.jpg` 计为 orphan 而 FAIL_STOPPED；修复 `fdfce5a` 后，首次重跑仅在验收脚本解析 `._preview-manifest.json` 时失败（产品 verify 为 OK）。第二次重跑在真实 ExFAT SD 卡上以 **MOCK Lightroom** 完成 ENOTSUP/重试/重复/冲突检查（发布 7 次、预览复用 1 次真实 ENOTSUP）；另做独立真实 Lightroom + ExFAT 冒烟，曝光读回 0.5、JPEG 1600×1065。`NIKON001.DSC` 未变，付费 API 0 次；不代表批量或生产可靠性。见 [报告](MACOS_VALIDATION.md)、[首次重跑](../evidence/mac-r2-rerun/result.json)、[最终结果](../evidence/mac-r2-rerun2/result.json)。

2026-11-03 R1 Mac 真实 AI 会话：**授权重跑有限样本 PASS**。首次第 2 次请求 TRANSPORT 失败后停止并保留原证据；用户授权重跑并批准具体计划后，真实 DeepSeek + 真实 Lightroom 五阶段完成，核验 OK/mock=false，批准仅一条，RAW/JPG/曝光独立读回通过。累计 driver count=9/13，未重置额度；回归 135 passed、2 skipped。详见 [Mac 报告](MACOS_VALIDATION.md)、[重跑证据](../evidence/mac-r1/retry-1/result.json) 和[首次失败](../evidence/mac-r1/result.json)。未进入 R2。

| # | 功能 | 状态 | 证据 |
|---|---|---|---|
| 5 | 安全导片（扫描、SHA-256、临时文件+读回+硬链接无覆盖提交、最终读回、冲突检测、清单、日志、路径/软链接防护、断点重试、磁盘满/读失败处理；纯 NEF、纯 JPG、混合批次缺配对也不跳过） | 已完成且测试通过（Linux ext/overlay 文件系统上的合成字节；Mac 本机及外置 APFS 有有限样本验收；exFAT 目标已有 R2 单样本范围通过；SMB 待验证；纯 JPG 尚未在本次 Mac 试用目录上实机核验） | tests/test_ingest_acceptance.py（场景 1–10）；tests/test_ingest_unpaired_photos.py |
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
