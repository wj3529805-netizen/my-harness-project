# Gate 1 validation notes

- Initial editable install failed because the venv lacked setuptools. Installed the bundled `/usr/share/python-wheels/setuptools-78.1.1-py3-none-any.whl` offline; editable installation then succeeded.
- Initial unscoped pytest discovery collected the unrelated third_party-review DeepSeek SDK suite and failed with 21 missing-module collection errors. Project discovery is explicitly `tests/`, as specified by this project's layout. Those third-party tests were not changed or deleted.
- Lightroom, preview, MCP and reports are 尚未开发 in Stage A. No real Lightroom/macOS verification is claimed.
- First project acceptance run: 51 passed, one identity-conflict test failed because manifest temp parent was missing, masking IDENTITY_CONFLICT. Fixed parent creation; assertion retained.
- Second run: same test caught an existing batch manifest from another task's run 1. Manifest allocation now retries the next batch manifest number atomically without overwriting; task run remains in each event.
- Hard-link fallback: for unsupported-link errors, the engine acquires an exclusive per-destination `.cetacea-lock`, checks nonexistence again, and renames. This coordinates CETACEA writers; external writers that ignore the lock can race the rename. Prefer filesystems supporting hard links. Own fallback lock files are removed after release.

Final Gate 1 validation: `.venv/bin/python -m pytest -q` — 59 passed. No project test remains failing. All earlier failures above are retained as validation history.
- Commit attempt (`git add -A && git commit -m "feat(stage A): implement verified ingest workbench and Gate 1 acceptance tests"`) was blocked by the environment: `.git/index.lock` cannot be created because `.git` is read-only. Code remains uncommitted on phase1; no push attempted.

Stage B validation history: first full run was 57 passed, 2 failed. The failures exposed a missing human Lightroom scope and an ingest completion check that treated cooperative cancellation as full ingest completion. Fixed the scope and require all assets VERIFIED before skipping a completed ingest step; original assertions retained.

Stage C validation history:
- First full run: 65 passed, 1 failed (`test_real_mcp_interface_only`): fake stdio server initialization timed out in the existing real adapter. Investigating with the installed MCP 2.3.0 source; no assertions removed or weakened.

---
# 已知风险与未完成事项（Phase 1 收尾）

测试：Phase 1 收尾时 71 passed；Phase 2 Mock 阶段 75 passed；真实模型阶段无密钥/开关全量 90 passed、1 skipped，真实模型 opt-in 5 passed；本阶段无密钥/开关 103 passed、2 skipped（分别为 `tests/test_realmodel_optin.py`、`tests/test_realmodel_fullplan_optin.py`；Linux，Python 3.13）。开发过程中的失败与修复历史见上文。

1. **未在 macOS / 真实 Lightroom 上验证**任何东西。`RealLightroomMcpAdapter` 只对假 MCP 服务器做过接口测试；lightroom-mcp 实际返回格式（import_photos 无 photo id、export_photos 无文件名）按源码阅读做的假设，须在 Mac 上验收清单 A13 确认。
2. 真实适配器每次调用都启动一个 MCP 子进程（简单、隔离，但慢）；大批量时需改为长连接会话。
3. Mock 适配器的“已登记”状态在进程内存里；跨进程时以数据库 assets.lr_photo_id 为准。
4. 硬链接不可用时的回退（`.cetacea-lock` + rename）只对遵守锁的 CETACEA 写入者安全；外部写入者可能竞争。APFS 支持硬链接；exFAT/SMB 待验证。
5. 性能：扫描一次完整哈希，复制时再读源、读回临时文件、最终读回，共约 4 次读取；大卡（数百 GB）耗时较长，未做基准测试。
6. **开放风险，待用户决定**：`photo_list_sources` 会向 AI 返回已登记来源的绝对路径（会经 Harness 发送给 DeepSeek，可能暴露用户名、目录结构或卷名；AI 不能据此读写任意路径）。此路径不在 2026-11-02 用户决定范围内；建议后续只返回来源 ID/标签，见 [数据流](DATA_FLOW.md)。
7. 磁盘满/权限错误通过故障注入和 monkeypatch 测试，并非真实磁盘满。
8. （Phase 1 原文，已被 Phase 2 部分取代）没有真实 AI 客户端联调。Phase 2 之后：Harness 的真实 MCP 客户端及 DeepSeek 已小规模联调；Codex/Claude 客户端未联调。
9. 私有 GitHub 仓库未能核查（需 GitHub App 授权）。
10. 无 Windows 支持；POSIX 专用调用（O_NOFOLLOW、os.link）。
11. 代码风格偏紧凑（Codex 生成），后续可重构；测试覆盖了行为但未做覆盖率统计。
12. 开发流程说明：Codex 因 `.git` 沙箱只读无法提交；提交由编排者完成。Codex 在 Stage B/C 两次卡在调试 mcp 2.x stdio 细节时被中止，编排者**直接修改了**：tests/fake_lightroom_mcp.py（改用 `server.run()`）、real_mcp.py（客户端结果字段为 snake_case：`is_error`、`structured_content`）、tests/test_mcp.py（audit_log 列名 actor）、report.py（丰富 Markdown 报告）。
13. CLI: 未批准就 execute 会输出 Python 堆栈（NotApproved）而不是友好提示；已被拒绝，功能正确，仅体验问题。

---
# Phase 2：deepseek-harness 接入的已知风险与未验证项

状态：此前真实 DeepSeek 的 5 个场景各 1 次、17 次请求；完整计划另采样 1 次、8 次请求。均仅 Linux，Lightroom 为 MOCK；不构成可靠性保证；Harness 仍为实验性/未审计。

1. **真实模型样本有限**：仅一个非确定性模型、每场景一次，不构成可靠性或安全保证。此前 `lightroom_import_verified` 被拒是因为模型规划时未传 `stages`，core 默认仅 `ingest`，批准的计划没有 Lightroom 阶段；该拒绝正确，检查保留。AI 有 Lightroom scope，但始终没有 approve 权限。新 MCP 默认完整计划后，一次真实模型采样经一次人工批准完成 MOCK 预览核验；见 [完整计划](FULLPLAN.md)。
2. **Harness 实验性/未审计**：其 SAFETY.md 自述。固定提交，但我们未做安全审计；仅审阅了安装脚本、MCP 客户端、测试驱动和 flock.c。
3. **Harness 默认给模型 bash/文件读写/web/子代理等工具**（已验证：不加限制时 headless profile 暴露约 40 个工具）。这会绕过 CETACEA “AI 无 shell/路径/删除”的契约。已提供 `harness/cetacea-restricted.patch.yml` 关闭这些工具，测试用“允许清单”断言模型只能看到 14 个 `mcp__cetacea__*` + 目标/待办/MCP 资源列表工具（并经变异验证：去掉限制则测试失败）。**任何真实模型部署必须带上这个限制文件**；它不是 Harness 的默认行为，使用者漏配就不安全。
4. **工具调用警告仅经 Mock 验证**：本项目 guard 在运行前检查静态能力表和工具面，逐轮检查缺少调用、工具失败及未知工具；要求调用时 `NO_TOOL_CALLS` 会令 `success=False` 并向 stderr 输出 WARNING。能力表不向提供商查询；真实 DeepSeek 只观察到有工具调用和允许无工具的正常拒绝，未用真实不支持工具调用的模型触发警告。
5. **从源码运行，没有构建全部产物**：`typert-loader` 条目因缺少未构建的 `lib/typert.host.js` 而不激活（日志里 “1 entry did not activate”，非致命，仅影响 Harness 的 RPC 类型层，不影响 MCP/工具/agent 循环）。其余未构建的桌面/Web 部件未使用。
6. **`--ignore-scripts`**：没跑 Harness 的 postinstall（lefthook、node-pty）；若以后用到终端/pty 功能需另行评估。flock 原生插件由本机 gcc 编译，非官方预编译。
7. **检出不入库**：`third_party-review/deepseek-harness` 被 git 忽略，不 vendoring；换机器需按 harness/README.md 复现；测试在缺依赖或 Node < 24.9 时**跳过**（带原因），因此 CI/新机器上这 4 个测试所在模块会整体显示为 1 skipped 而非 passed。
8. 运行器把覆盖文件临时复制进 Harness 检出（每次运行独立目录，退出时清理），因此检出必须可写；并发运行互不干扰但未做压力测试。
9. 审计日志里 AI 的 actor 字符串为 `ai:ai:mcp`（Phase 1 遗留命名：actor_id 默认值已带 `ai:` 前缀），人工为 `human:cli`；仅外观问题，既有测试按前缀判断，未改动。
10. 仍未验证：macOS、真实 Lightroom Classic、APFS/exFAT/SMB、真实相机卡、真实客户数据。Linux 上的 MOCK 结果不代表 Mac 实机结果。
11. 开发流程说明：Codex 本阶段仅用于只读代码审阅（`gpt-6.1-terra`，reasoning high），其意见已采纳并修复（见 git 历史）；其余代码、测试、文档由编排者直接编写。

12. **多轮驱动验证**：此前沙箱启动超时只反映该环境限制；用户随后在沙箱外完成测试并全部通过。Mock 覆盖多轮、纯文本模型的 `NO_TOOL_CALLS`、`NOT_APPROVED`、预算退出码 4、ledger、14 个 CETACEA 加 7 个无害工具及缺密钥退出码 5。真实运行首次未批准场景先查状态并拒绝执行，原测试误期待 `NOT_APPROVED` 而失败；已调整该测试，并用独立强制调用场景验证该错误路径。
13. 真实 overlay 关闭 session-title、web、telemetry 条目；Harness 错误/诊断 stderr 被丢弃，提供商失败仅显示 `session failed`，排障信息有限。
14. 驱动的 30 次请求上限因竞争最多超出 1 次；ledger 无跨进程锁，不能供并发进程共享。
15. 密钥仅由 `DEEPSEEK_API_KEY` 传入，但必须进入 Harness 子进程环境；依赖 Harness 不记录密钥。仓库及证据已 grep 验证不含密钥值，Harness 自身网络及日志行为未审计。2026-11-02 用户在聊天中表示“没问题 可以交给deepseek”，接受发送包含真实客户数据的工具结果，范围为订单 ID、摄影师 ID、批次标签、文件名、文件大小、SHA-256 哈希、图库相对路径、任务/阶段状态和 Lightroom 状态文字。照片像素或文件内容不得发送，当前没有工具返回文件字节；该决定不覆盖未来返回文件内容或缩略图的工具，也不改变 DeepSeek 自身的数据保留条款，用户仍负责审阅适用条款。`photo_list_sources` 返回的来源绝对路径不在决定范围内，仍是开放风险，建议后续只返回来源 ID/标签，待用户决定。详见 [数据流](DATA_FLOW.md)。

16. **完成后重执行的配置检查**：即使任务已 `COMPLETED`，再次执行仍检查审批和快照；完成后若相关配置改变，会返回 `PERMISSION_DENIED`，而非直接无操作返回。这是可接受的当前行为。
17. **合并与测试环境**：`mac-validation` 分支尚未合并；本阶段源文件只改动 `core.py` 和 `mcp_server.py`，合并时需核对。MCP stdio 测试在 Codex 沙箱外通过；先前未验证仅是 Codex 沙箱限制。
