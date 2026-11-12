# Gate 1 validation notes

## Lightroom 批量登记 — 2026-11-10：离线回归通过，真实测速待用户执行

本次基于 `2ca1453`，在 `codex/lr-batch-register` 实现默认 100 张、上限 200 张的
单批单写事务、整次登记共用 stdio 会话、批量 metadata 核对及部分失败续登。
工作流也改为一次提交全部已验证待登记项，移除逐张状态探测。HOME 桥行为保留。
固定版本 MIT Lua 扩展与隔离运行时准备器均纳入版本控制；未加载或修改全局插件，
未操作真实 Lightroom / 正式 catalog / 客户照片或 DeepSeek ledger。
安装、用法及边界见 [LIGHTROOM_BATCH.md](LIGHTROOM_BATCH.md)。

测试历史如实保留：实现中间一次聚焦运行 `30 passed, 1 failed`，原因是测试夹具已迁移至
`import_photos_batch` 而适配器仍处于旧 `import_photos` 实现。批量实现接通后，相关聚焦
测试先后为 `146 passed`、补充异常边界后 `154 passed`；工作流相关回归 `94 passed`。
Lua 离线测试实际执行 MOCK catalog 对象，包含 134 张单事务、去重、部分失败续登、
取消、事务异常及进度报告异常，共 `11 passed`。这些都不代表真实 Lightroom 验收。

完整命令（显式使用本工作树源码，只借用既有 Python 3.13 环境）：

```sh
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 \
  "$HOME/Documents/ChatGPT/AI工作台/my-harness-project/.venv/bin/python" -m pytest -q -rs
```

首次全量为 **374 passed, 4 skipped in 49.23s**，退出码 0。
补充两项连接安全回归后，第二次全量为 `1 failed, 376 passed, 4 skipped in 50.58s`：
`test_tracked_tree_is_clean` 发现新增测试说明包含本机绝对 HOME 路径（`R-HOME`）。
随后把新增说明改用 `$HOME` / 工作树相对路径，未更改隐私规则或测试。
将全部 15 个候选文件逐路径暂存后，隐私及批量聚焦回归 `56 passed`；
最终全量 **377 passed, 4 skipped in 50.58s**，退出码 0。
四个跳过为两组未安装 Harness
依赖的集成模块及两组未启用真实模型的模块；没有为这次变更安装或调用网络/付费依赖。
单独核对跳过原因及 HOME 回归为 `8 passed, 4 skipped`，退出码 0。
新增的 Lua 测试在本机已有 Lua 动态库上执行，未跳过。

剩余限制：用户须手动停用原插件并加载隔离替换副本；未重测真实 134 张，不能宣称已经达到
1–2 秒/张。SDK 要求存在查询位于写锁外，并行 UI 导入相同路径可能影响 `added/existing`
分类计数；请保持单一导入者。超时后事务可能仍在运行，连接恢复先批量核对再重试缺失路径。
catalog 守卫仍使用 `pgrep/lsof`，没有窗口标题依赖；新增回归证明空标题不影响打开文件的判断，
正式 catalog 同时打开时拒绝继续。

## R2 real ExFAT — 2026-11-03：PASS_IN_SCOPE（单样本），失败历史保留

原始 R2（`2a8d669`，[evidence/mac-r2/](../evidence/mac-r2/result.json)）因 `preview.verify` 将 AppleDouble `._*.jpg` 计为 orphan 而 FAIL_STOPPED；修复为 `fdfce5a`。首次重跑的产品 [verify 为 OK/mock=true](../evidence/mac-r2-rerun/mock-verify-preview.json)，仅验收脚本清单读回误解析 `._preview-manifest.json` 为 UTF-8 JSON 而停止，整轮仍为 [FAIL_STOPPED](../evidence/mac-r2-rerun/result.json)。原始失败证据保留。

[第二次重跑](../evidence/mac-r2-rerun2/result.json) **PASS_IN_SCOPE**：真实 ExFAT SD 卡上以 **MOCK Lightroom** 完成 ENOTSUP/重试/重复/冲突检查，真实发布 ENOTSUP 7 次、预览复用 1 次；另有独立真实 Lightroom + ExFAT 冒烟，曝光读回 0.5、JPEG 1600×1065。`NIKON001.DSC` 未变，付费 API 0 次。仅单样本范围通过，不代表真实 Lightroom 故障重试、整卡/批量、SMB 或生产可靠性；不遵守 `.cetacea-lock` 的外部写入者仍可能竞争。详见 [报告](MACOS_VALIDATION.md)。

## R1 Mac real AI — 2026-11-03：授权重跑有限样本通过

用户后续授权免费 curl 检查、脱敏错误诊断及原 13 次总额内一次重跑，再明确批准具体计划。重跑三轮耗用 7 次，累计 driver count=9（保留首次 2 次），未重置计数。实际 DeepSeek + 真实 Lightroom 完成五阶段、一次人类 CLI 批准，批准前执行拒绝/删除和 shell 请求拒绝，模型与 CLI 均核验 OK/mock=false，RAW 目标读回及曝光/JPG 独立检查通过。[报告](MACOS_VALIDATION.md)、[重跑结果](../evidence/mac-r1/retry-1/result.json)。

三个不带 key 的 curl HEAD 均 HTTP401、TLS 校验通过，未见拦截页；系统代理开启，不能据此证明完全不经代理或流式连接长期稳定。首次 TRANSPORT 根因仍未知，本轮未复现；已开启仅错误的脱敏诊断，普通 stdout/stderr、请求头/正文不作为错误对象序列化。成功请求后的 AbortError 连接清理和可选 typert-loader 缺失模块的启动错误亦如实保留，不能把任意 stderr 行等同于模型失败。当前测试仍仅公开 Nikon Z6 单样本、专用测试 catalog，非客户数据、非生产可靠性证明；两项实网 pytest 模块仍跳过（真实会话另行运行），全量回归 135 passed/2 skipped。R2 后续结果见上节；R3–R5 尚未开始。

## R1 Mac real AI 首次失败 — 2026-11-03：FAIL_STOPPED，历史

`mac/R1` 基于路线图 `0142bbc`。真实 DeepSeek 第 2 次模型请求报 `DeepSeek Messages transport failed`（TRANSPORT），尚未生成计划；仅来源/订单/真实 Lightroom 状态查询成功。按路线图停止，没有自动重试或进入 R2。驱动计数 2，失败请求计费未知；不能将 turn_done 或 mock=false 状态查询当完整验收通过。运行器抑制提供商 stderr，根因未证实。全部任务/批准/资产/步骤/预览为 0，源快照不变，库及预览为空；后续验收均 NOT_RUN。见 [报告](MACOS_VALIDATION.md)、[原始事件](../evidence/mac-r1/real-session.jsonl)、[结果](../evidence/mac-r1/result.json)。

付费前发现 60 秒工具超时接近既有 58.389 秒真实执行；本分支调为 20 分钟，离线回归 11 passed，尚无本轮真实完整执行证明。首次启动缺工作目录及证据汇总工具集合断言的辅助错误均有记录，未导致新增 API 请求或照片写入。

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

1. **Phase 1 收尾时的历史状态：未在 macOS / 真实 Lightroom 上验证**任何东西。`RealLightroomMcpAdapter` 只对假 MCP 服务器做过接口测试；lightroom-mcp 实际返回格式（import_photos 无 photo id、export_photos 无文件名）按源码阅读做的假设，当时须在 Mac 上验收清单 A13 确认；后续验收见下方 macOS 记录。
2. 历史逐调用启动 MCP 的登记瓶颈已在本次批量实现中修复：一次 `register()` 复用会话，瞬断才重连。预设、导出等非登记调用仍使用既有单次连接行为。
3. Mock 适配器的“已登记”状态在进程内存里；跨进程时以数据库 assets.lr_photo_id 为准。
4. 硬链接不可用时的回退（`.cetacea-lock` + rename）只对遵守锁的 CETACEA 写入者安全；外部写入者可能竞争。APFS 支持硬链接；exFAT 已有 R2 单样本范围通过（文件系统检查使用 MOCK Lightroom，另有真实 Lightroom 冒烟），SMB 待验证。
5. 性能：扫描一次完整哈希，复制时再读源、读回临时文件、最终读回，共约 4 次读取；大卡（数百 GB）耗时较长，未做基准测试。
6. **已接受的决定（2026-11-02）**：用户表示“可以，没问题”，接受 `photo_list_sources` 向模型返回已登记来源的绝对路径，并经 Harness 发送给 DeepSeek；路径可能暴露用户名、目录结构或卷名，AI 不能据此读写任意路径。此项决定仅覆盖该工具的来源路径；未来若工具返回文件内容或缩略图，或 DeepSeek 保留条款变化，须重新决定。见 [数据流](DATA_FLOW.md)。
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
10. 本阶段原记录：当时尚未验证 macOS、真实 Lightroom Classic、APFS/exFAT/SMB、真实相机卡和真实客户数据。后续 Mac 样本验收见下方记录；合并后的完整计划仍须重新验收。Linux 上只能运行 Mock Lightroom 测试，MOCK 结果不代表 Mac 实机结果。
11. 开发流程说明：Codex 本阶段仅用于只读代码审阅（`gpt-6.1-terra`，reasoning high），其意见已采纳并修复（见 git 历史）；其余代码、测试、文档由编排者直接编写。

12. **多轮驱动验证**：此前沙箱启动超时只反映该环境限制；用户随后在沙箱外完成测试并全部通过。Mock 覆盖多轮、纯文本模型的 `NO_TOOL_CALLS`、`NOT_APPROVED`、预算退出码 4、ledger、14 个 CETACEA 加 7 个无害工具及缺密钥退出码 5。真实运行首次未批准场景先查状态并拒绝执行，原测试误期待 `NOT_APPROVED` 而失败；已调整该测试，并用独立强制调用场景验证该错误路径。
13. 真实 overlay 关闭 session-title、web、telemetry 条目；Harness 错误/诊断 stderr 被丢弃，提供商失败仅显示 `session failed`，排障信息有限。
14. 驱动的 30 次请求上限因竞争最多超出 1 次；ledger 无跨进程锁，不能供并发进程共享。
15. 密钥仅由 `DEEPSEEK_API_KEY` 传入，但必须进入 Harness 子进程环境；依赖 Harness 不记录密钥。仓库及证据已 grep 验证不含密钥值，Harness 自身网络及日志行为未审计。2026-11-02 用户在聊天中表示“没问题 可以交给deepseek”，接受发送包含真实客户数据的工具结果，范围为订单 ID、摄影师 ID、批次标签、文件名、文件大小、SHA-256 哈希、图库相对路径、任务/阶段状态和 Lightroom 状态文字。照片像素或文件内容不得发送，当前没有工具返回文件字节；该决定不覆盖未来返回文件内容或缩略图的工具，也不改变 DeepSeek 自身的数据保留条款，用户仍负责审阅适用条款。用户另于 2026-11-02 表示“可以，没问题”，接受 `photo_list_sources` 的来源绝对路径经模型及 Harness 发给 DeepSeek；路径可能暴露用户名、目录结构或卷名。该项决定仅覆盖此工具；未来工具返回文件内容或缩略图，或 DeepSeek 保留条款变化时须重新决定。详见 [数据流](DATA_FLOW.md)。

16. **完成后重执行的配置检查**：即使任务已 `COMPLETED`，再次执行仍检查审批和快照；完成后若相关配置改变，会返回 `PERMISSION_DENIED`，而非直接无操作返回。这是可接受的当前行为。
17. **合并与测试环境**：合并前记录：`mac-validation` 分支当时尚未合并；本阶段源文件只改动 `core.py` 和 `mcp_server.py`，合并时需核对。MCP stdio 测试在 Codex 沙箱外通过；先前未验证仅是 Codex 沙箱限制。
18. **合并后待 Mac 重新验证**：含预设及导出快照的 `plan_digest`、`photo_execute_import`、`photo_retry_task`，以及 Harness/DeepSeek 驱动的完整计划路径，尚未在 Mac 上结合真实 Lightroom 重新验证。Linux 只能运行 Mock Lightroom 测试；此前 Mac 验收是合并前的历史记录。

---
## macOS validation update — 2026-11-02

详见 [MACOS_VALIDATION.md](MACOS_VALIDATION.md) 和 evidence/mac-acceptance/。基线 macOS 71/71；本次修复和新增回归后 98/98，真实独立 Lightroom catalog 的公开 Nikon Z6 NEF 登记、预设、导出、缺失检测、重复请求、批次关闭/恢复通过。先前“未做任何 macOS/真实 Lightroom 验证”的文字是开发期历史，不能再用来描述本次样本范围。

本次新增失败历史：Bash 3.2 中文括号变量解析失败；第一版合成 DNG 被 Adobe 以 dng_error_unsupported_raw 拒绝；全局禁用硬链接的新回归揭示清单不支持回退，随后导出恢复新回归揭示 SQLite state="FAILED" 与 failed 列冲突；慢调用回归在旧 300 秒租期下暴露 recover 可夺走活任务。上述产品问题已修并保留回归。真实调用的底层错误现不会仅剩 TaskGroup 摘要。无硬链接的锁回退仍有不守锁外部写入者 race。

首次验收时实体卡/读卡器、真实外置 exFAT/SMB、实际 AI 产品客户端（可选 A14）、Z6 III HE/HE★、断电/强杀以及 Windows 仍未通过实机验收；实体卡/读卡器的后续有限样本见下节。A12 关闭点在两张照片之间，不能当作单次 catalog 写入中断证明。样片发行 README 与内嵌版权许可文字有差异，保留来源及作者信息，照片和预览不随 Git 发布。已知 CLI NotApproved 堆栈体验问题仍在。


## Physical media follow-up — 2026-11-02

详见 [MACOS_DEVICE_VALIDATION.md](MACOS_DEVICE_VALIDATION.md)。实体SD与USB卡各1张选中NEF只读导入本机和外置APFS通过；源哈希/mtime不变、目标哈希读回、同异哈希保护、外置APFS的完整Mock流程及部分失败重试通过。源是有界单文件预扫描，不代表整卡递归扫描/吞吐。

macOS ENOTSUP=45和EOPNOTSUPP=102不相等，两处回退遗漏ENOTSUP已由新增参数化回归重现后修复；全套100 passed。真实exFAT目标仍未运行：两个建镜像工具失败，未格式化任何原有设备或在卡上写探针。外置盘曾在拷贝前掉线，挂载守卫停止操作，重连核对UUID后才继续。

两张选中Z6III NEF的外置副本还完成真实测试catalog登记、+0.50预设读回、单张JPG导出和verify-preview；原始NEF与库副本不变。该设备补充未独立辨识HE/HE★子类型、未逐项核对相邻XMP/ACR，不能扩展为每种压缩或整卡生产验收。

## phase2-merged Mac follow-up — 2026-11-02

被验收代码 `08fcfd9`；完整结果及证据见 [MACOS_VALIDATION.md](MACOS_VALIDATION.md) 的本轮章节与 `evidence/mac-acceptance-merged/`。Python 3.13 最终 **132 passed、2 skipped**；首轮缺 Harness 依赖导致 120 passed、4 skipped 的日志也保留，补齐固定依赖后未修改产品或测试断言。两个 DeepSeek 实网模块未运行，不能视为模型效果验收。

真实三照片中断测试中，按计划在第一张登记后正常退出测试 Lightroom；后两张插件断连报错，任务实际 FAILED（`lr_register: 2 failed`），没有伪报完成。重开同一测试 catalog 后通过 `photo_retry_task` 补两张、跳过一张，最终全流程完成且未新增批准。此为预期故障刺激及恢复通过，不是单次 catalog 写入中强杀/断电、PAUSED 租期过期恢复或生产可靠性证明。

本轮公开 Nikon Z6 样片、测试 home/catalog、源及库哈希和 XMP/ACR 集合通过；920 秒为代码常量及真实执行时租期采样，不是耗时 920 秒的实机压测。批准后修改工作台预设选择或导出质量会在工作前拒绝；Lightroom 内部同名/同 UUID 预设内容变化的检测、旧无快照计划兼容路径未在本轮实机验收。既有 CLI NotApproved 堆栈体验问题及其他平台/格式/设备限制不因此消除。
# AppleDouble follow-up (2026-11-03)

The R2 exFAT failure counted macOS AppleDouble companions as preview orphans. Source scans now skip magic-identified regular AppleDouble files without including them in the digest; output enumeration ignores those files and regular files named exactly `.DS_Store`. Non-magic `._` files remain ordinary files. Fix `fdfce5a` has Linux tests and a subsequent real ExFAT **PASS_IN_SCOPE** in `evidence/mac-r2-rerun2/result.json` (MOCK Lightroom filesystem checks plus a separate real Lightroom smoke; single sample). Both earlier failure records remain unchanged; see the R2 section above.

Linux validation: full suite on the Linux box passed (128 passed, 4 skipped). Mock/Linux results only; not a macOS or Lightroom pass.

## R5 隐私残留 — 2026-11-03

当前树已脱敏，但公开仓库的 Git 历史仍含原始标识，未重写。harness UUID、卷名、项目文件夹名，以及历史旧样片的 SHA、第三方版权文字和相机序列号仍保留；新样片内嵌机身和镜头序列号经所有者同意公开。所有者已决定保留这些标识并确定样片许可，见 [最终验收](FINAL_ACCEPTANCE.md) 和 [样片许可](../samples/LICENSE.txt)。

## 日常 Lightroom 登记入口 — 2026-11-12

首轮新增入口测试为 **3 failed、11 passed**：持久化 fake MCP 在主线程创建 SQLite
连接，而 MCP SDK 在 worker thread 调用同步工具，触发 `sqlite3.ProgrammingError`。
已将该 MOCK 连接显式允许跨线程使用，并通过锁串行访问；保留原有恢复、去重和守卫断言，
没有弱化测试。修正后定向回归 **78 passed**；最终全量结果见
[2026-11-12 验收](FINAL_ACCEPTANCE.md)。

崩溃恢复自动化使用真实 stdio MCP 子进程与持久化 MOCK catalog，在第二批写入部分记录后
`os._exit(86)`，重开子进程续登记；不代表真实 Lightroom 的事务提交或回滚行为。
真实 Lightroom 写入中途崩溃、SMB/NAS 非生产共享仍未在本任务验证。
日常入口不重复导片助手的复制或 SHA-256 字节验证；只读扫描导入目录并核对 catalog
精确路径登记。报告含本地绝对路径，权限为当前用户读写，不应随公开仓库提交。
