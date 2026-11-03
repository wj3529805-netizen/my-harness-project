# macOS validation — 2026-11-02

## R2 修复后重跑 — 2026-11-03：PASS_IN_SCOPE（单样本）

原始 R2（`2a8d669`，`evidence/mac-r2/`）因 `preview.verify` 将 AppleDouble `._*.jpg` 伴随文件计为 orphan 而 **FAIL_STOPPED**，历史记录保留如下。修复为 `fdfce5a`。首次重跑 `evidence/mac-r2-rerun/` 的产品核验已为 [OK/mock=true](../evidence/mac-r2-rerun/mock-verify-preview.json)，但验收脚本在清单读回时误把 `._preview-manifest.json` 当 UTF-8 JSON，发生 UnicodeDecodeError 并停止；这是验收脚本解析失败，不能记作产品 verify 失败或整轮通过。[首次重跑结果](../evidence/mac-r2-rerun/result.json)。

第二次重跑 [result.json](../evidence/mac-r2-rerun2/result.json) 为 **PASS_IN_SCOPE**：

- **真实 ExFAT SD + MOCK Lightroom**：ENOTSUP 回退、部分失败后重试及预览复用、相同内容重复导入、不同内容同名冲突检查通过；真实发布 ENOTSUP=45 共 **7 次**，预览复用 **1 次**，未注入 errno。[文件系统结果](../evidence/mac-r2-rerun2/filesystem-result.json)、[系统调用检查](../evidence/mac-r2-rerun2/real-enotsup-checks.json)、[重复/冲突](../evidence/mac-r2-rerun2/repeat-and-conflict.json)。
- **独立真实 Lightroom + ExFAT 冒烟**：mock=false，曝光独立读回 **0.5**，JPEG **1600×1065**，RAW/JPEG 目标 SHA-256 读回通过；此项不替代上述 MOCK 故障/重试检查。[曝光读回](../evidence/mac-r2-rerun2/real-develop-readback.json)、[预览核验](../evidence/mac-r2-rerun2/real-verify-preview.json)。

`NIKON001.DSC` 未变，付费 API 调用 **0 次**。这是单样本范围通过，不代表整卡吞吐、所有设备/格式、SMB 或生产可靠性；不遵守目标锁的外部写入者竞争风险仍在。

## R2 原始 ExFAT SD 目标 — 2026-11-03：FAIL_STOPPED（历史）

从更新后的 `phase1/80acebb` 建立 `mac/R2`。先用 `diskutil info` 确认内置 SDXC 读卡器的 `disk7s1` 为 **ExFAT**，挂载点为 `/Volumes/NIKON Z6_3  1`（两个空格后接 1），可用约 126.84 GB。只读列出原有 6 个文件和 3 个目录：`.fseventsd/`、`.Trashes/`、`NIKON001.DSC`，无照片。用户核对后明确批准仅在新目录 `Cetacea-R2-Test-20261103/` 内进行不超过 500 MB 的测试，不格式化、不删除或覆盖原有文件。[设备信息](../evidence/mac-r2/disk7s1-diskutil-info-text.json)、[原有完整清单](../evidence/mac-r2/sd-existing-content-list.txt)、[写入授权](../evidence/mac-r2/card-write-authorization.json)。同名的 256 GB USB TypeB 卡只核对设备信息，没有对其执行文件测试。

**本轮整体未通过，已在首个非预期失败处停止；没有修复产品代码、清理测试现场或继续测试。** 使用本机公开 Nikon Z6 RAW 的两份副本和合成 XMP 哨兵作为只读源。先使用明确标记为 MOCK 的 Lightroom 导出故障，构造“一张预览成功、另一张失败”的状态；这是故障刺激，不是真实 Lightroom。文件系统及工作台发布/重试代码实际运行在 SD ExFAT，观察器原样调用真实 OS 函数，未注入或替换 ENOTSUP。[可审查脚本](../evidence/mac-r2/run_r2.py)、[真实系统调用](../evidence/mac-r2/real-filesystem-events.jsonl)。

| R2 项目 | 实际结果 |
|---|---|
| 实际导入发布/清单硬链接回退 | 已观察真实 `ENOTSUP=45`，随后重命名发布成功；3 个导入资产目标 SHA-256 独立读回一致 |
| 实际预览复用硬链接回退 | 已观察 `_lightroom_stage` 的真实 `ENOTSUP=45`；成功旧预览复制到新 run，旧文件哈希/mtime/inode 保留，新副本哈希一致、inode 不同 |
| 部分失败后的导出重试 | lr_export 重试为 succeeded=1、skipped=1、failed=0，但最终 preview_verify **FAILED**，任务仍 FAILED/run_count=2 |
| 最终预览核验 | **FAIL**：expected_count=2、mapped_count=2，missing/failed/size_violations 为空，却出现两个 `._*.jpg` orphans |
| 相同内容重复导入、不同内容同名冲突 | **NOT_RUN**，在最终预览失败后即停止 |
| 单独真实 Lightroom + ExFAT 流程 | **NOT_RUN**，没有向 Lightroom 发出本轮照片处理请求 |

`file` 工具确认两个所谓 orphan 均为 **AppleDouble encoded Macintosh file**（4096 字节），不是导出的照片。只读源码检查定位 `preview.verify`：它递归收集所有后缀为 `.jpg/.jpeg` 且不在映射中的路径，没有排除这些伴随文件，于是把 `._ast_…jpg`、`._r2_tester_b_…jpg` 判为多余 JPG。原本登记的 JPEG 均可解码、SHA-256 与记录相符，仍不能把失败核验改写为通过。[失败数据库/阶段明细](../evidence/mac-r2/failure-database.json)、[文件清点](../evidence/mac-r2/failure-target-file-inventory.json)、[只读诊断](../evidence/mac-r2/failure-analysis.json)、[原始失败](../evidence/mac-r2/result.json)。真实适配器面对这些伴随文件的行为未测，不能扩展此结果为其通过或失败。

原有所有清点条目仍存在，`NIKON001.DSC` 的 SHA-256/mtime/inode 未变；两个本机测试源快照也未变。系统维护的 `.fseventsd/.Trashes` 只列出，不声称它们的内容不可变化。测试目录保留约 **52.14 MB**；macOS 还自动生成相邻的 `._Cetacea-R2-Test-20261103` AppleDouble 文件，亦保留未清理，没有把它隐瞒为“卷根无新增条目”。没有格式化或删除任何原有文件，未调用付费 API。[原有文件前](../evidence/mac-r2/preexisting-nikon-file-before.json)、[后](../evidence/mac-r2/preexisting-nikon-file-after.json)。

失败后仅进行只读文件/卷/数据库诊断和本机证据、文档写入。清单汇总最初把 `._…manifest.json` 当 UTF-8 JSON，出现 UnicodeDecodeError；仅修正了证据解析器的文件选择，未修改产品核验或重复运行，原错误与说明保留于[诊断说明](../evidence/mac-r2/failure-inspection-note.json)。当时停止并等待用户决定；后续修复和两次重跑见上节，不改写原始失败结论。

## R1 授权重跑 — 2026-11-03：本次范围 PASS

用户授权先进行不带 key 的 curl 检查、打开仅错误的脱敏输出，并在原累计最多 13 次请求内重跑一次。默认路径、`--noproxy '*'` 和系统配置代理三次 HTTPS HEAD 都返回 401（未授权请求的预期响应），TLS 校验为 0/通过；代理 CONNECT 返回 200。未发现证书错误或拦截页，但不能据此保证流式连接持续稳定。[网络证据](../evidence/mac-r1/retry-1/)、[代理配置摘要](../evidence/mac-r1/retry-1/proxy-settings.json)。curl 未携带 API key，也未产生模型请求。

curl 终端文本保留实际响应，仅为 Git 空白检查移除了行末 ASCII 空格/tab；原文件 SHA-256 和可精确复原的逐行后缀编辑均保留，HTTP 状态、头、证书及计时未作语义修改。[规范化记录](../evidence/mac-r1/retry-1/curl-text-normalization.json)。

运行器现将 stderr 先交给错误过滤器，普通启动输出丢弃，密钥精确值、常见凭据字段和 Bearer 值在终端/落盘之前脱敏。DeepSeek 诊断只记录错误的 name/code/message/status/cause，不序列化请求、headers、body 或 stack；只读观察 undici 错误，不改网络请求、TLS 或重试策略。实际成功请求后观察到 AbortError；固定 Harness 的 generate-finally 会主动 abort consumer 清理连接，不能仅凭此把成功的 turn/end=completed 判成失败。诊断相关回归 19 passed，全量 **135 passed、2 skipped**。[回归](../evidence/mac-r1/retry-1/diagnostic-regression.txt)、[全量](../evidence/mac-r1/retry-1/pytest-full.txt)。

原 ledger 保留 2，本轮规划、负向检查、批准后执行三轮分别 2、2、3 次，最终累计计数 **9/13**（本轮 7 次）。绝对配置上限保持 12，保留已说明的最多一次竞态余量；没有重置 ledger、追加额度或完成后继续请求。计数不是独立账单核对，首次失败请求是否计费仍以提供商为准。[累计计数](../evidence/mac-r1/request-ledger.json)、[三轮摘要](../evidence/mac-r1/retry-1/model-turn-summaries.json)。

真实模型生成默认五阶段计划后在 WAITING_APPROVAL 停下；受控未批准执行恰调用一次，实际返回 NOT_APPROVED，模型明确拒绝删除和 shell 请求。批准前资产仍 PLANNED、无步骤或预览，源不变，库和预览为空。[计划](../evidence/mac-r1/retry-1/plan.json)、[批准前检查](../evidence/mac-r1/retry-1/preapproval-checks.json)。用户在本聊天审阅并明确批准任务 `tsk_e1ac50d0ffc24f5d801665f1237893ee` 和摘要 `5c993f58ae714f7dc77038a3c94ba9b76ff460390042edecbb633f8b715291c9` 后，才通过外部操作端 CLI approve；AI 无批准工具，实际批准行仅一条且摘要相符。[批准记录](../evidence/mac-r1/retry-1/human-cli-approval.json)。

| 验收项 | 结果与证据 |
|---|---|
| 真实 DeepSeek → 受限 Harness → CETACEA → 真实 Lightroom | PASS；实际工具面精确为 14 个 CETACEA 工具 + 7 个允许的 Harness 工具，三轮 turn/end 均 completed。[原始事件](../evidence/mac-r1/retry-1/real-session.jsonl) |
| 批准后由 AI 执行完整计划 | PASS；`photo_execute_import` 恰调用一次，任务 COMPLETED、run_count=1、error=null、mock=false，ingest/lr_register/lr_preset/lr_export/preview_verify 五个步骤各完成一次。[最终任务](../evidence/mac-r1/retry-1/final-task.json)、[数据库与审计](../evidence/mac-r1/retry-1/final-database.json) |
| 模型及独立 CLI 核验 | PASS；模型在执行返回 COMPLETED 后才调用 photo_verify_preview，OK/mock=false；独立 CLI verify-preview 同样 OK/mock=false。[CLI 核验](../evidence/mac-r1/retry-1/cli-verify-preview.json) |
| 目标读回、实际预设及 JPEG | PASS；RAW 目标重新打开读回 SHA-256，与计划及源一致；真实 Lightroom 曝光独立读回 0.5；JPG 完整解码 1600×1065，读回 SHA-256 与预览记录一致。[最终检查](../evidence/mac-r1/retry-1/final-checks.json)、[曝光读回](../evidence/mac-r1/retry-1/develop-readback.json) |
| 测试边界和批准权限 | PASS；执行前后只核对独立测试 catalog 的打开文件名，不读 .lrcat 内容；源 SHA-256/mtime/inode 前后一致，无新增库 XMP/ACR；批准仅来自人类 CLI，AI 从未批准。[最终 catalog 守卫](../evidence/mac-r1/retry-1/catalog-guard-final.json)、[源快照](../evidence/mac-r1/retry-1/source-after.json) |

[完整结论](../evidence/mac-r1/retry-1/result.json)。本轮只用一张已说明来源/许可证差异的公开 Nikon Z6 样片和专用测试 catalog，没有客户数据、生产 catalog、NAS、实体卡或额外安装。仍只是一次有限样本，不代表生产可靠性、所有机型/HE★、大批量或所有网络条件；核心资产租期仍为 920 秒，本轮未做 920 秒实耗压测。首次 TRANSPORT 的根因没有被证明，本轮没有复现，不能声称已永久修复网络。开启诊断后亦可见固定 Harness 可选 typert-loader 缺少 typert.host.js 的启动错误；实际白名单工具与完整流程成功，不据此宣称这些可选模块通过。密钥完整值及常见前缀扫描零命中。[扫描](../evidence/mac-r1/retry-1/secret-scan-final.json)。会话已结束，未进入 R2；本轮新提交推送仍待用户授权。

## R1 首次真实 AI 会话 — 2026-11-03：FAIL，历史记录

以下保留首次失败时的结论；后续授权检查和成功重跑见上节，不改写首次失败结果。

基线 `phase1/0142bbc`，工作分支 `mac/R1`。用户授权仅本次 R1、最多 13 次 DeepSeek 计费请求；驱动上限设 12，保留已说明的最多一次取消竞态余量。使用现有 `deepseek-flash`、thinking 关闭、provider 自动重试 0。**驱动记录 2 次模型请求，第 2 次报 `DeepSeek Messages transport failed` / `TRANSPORT`，未生成计划，R1 未通过。** 未自动重试，未使用剩余额度，未进入 R2。失败请求是否计费以提供商为准。

准备仅用公开 Nikon Z6 样片一份、全新 `acceptance-data/mac-r1/` home/源/库/预览，以及原有独立测试 catalog。没有客户数据、生产 catalog、NAS 或新依赖安装。源只读快照及 catalog 打开文件名守卫保留，没有读取 `.lrcat` 内容。[预检](../evidence/mac-r1/preflight.json)、[环境检查](../evidence/mac-r1/check-env.txt)、[catalog 守卫](../evidence/mac-r1/catalog-guard.json)。样片来源和许可证差异沿用下文说明。

本分支在付费请求前将真实 DeepSeek overlay 的 `toolCallTimeoutMs` 从 60000 改为 1200000（20 分钟）：此前真实完整执行已耗时 58.389 秒，原等待余量过小。该配置不改变核心 920 秒资产租期，也未宣称已通过真实长流程验收。离线 Harness session/gating 回归 **11 passed**。[回归日志](../evidence/mac-r1/offline-regression.txt)。Harness 临时 HOME 保持隔离；仅测试 home 的受信任 Lightroom 后端命令通过 `/usr/bin/env HOME=<当前用户HOME>` 使用原桥运行环境，未复制 token 或密钥。

无付费的 Mock 控制器先经受限 Harness 查询真实 Lightroom，状态连接且 `mock=false`；这只证明桥连通，不能充作真实 AI 验收。[桥事件](../evidence/mac-r1/readonly-bridge-events.jsonl)。真实模型第 1 步成功调用 `photo_list_sources`、`photo_list_orders`、`lightroom_get_status`，第 2 步发生 TRANSPORT 错误；turn/end 为 error，不能因随后仍输出 `turn_done` 就判成功。运行器抑制提供商诊断 stderr，现有证据不足以判断具体是网络、认证、额度或提供商故障，未猜测根因。[原始会话](../evidence/mac-r1/real-session.jsonl)、[计数](../evidence/mac-r1/request-ledger.json)。

| 验收项 | 结果 |
|---|---|
| 实际工具面：14 个 CETACEA 工具 + 7 个允许的 Harness 工具，无 shell/删除/文件读写/批准入口 | PASS，精确集合已核对 |
| 真实 Harness → Lightroom 只读状态 | PASS，mock=false |
| 完整计划与 WAITING_APPROVAL、批准前执行拒绝、越权请求拒绝 | NOT_RUN，尚未生成计划 |
| 人工 CLI 批准、完整执行、verify-preview、目标 SHA-256 读回 | NOT_RUN |
| 最终任务/批准/资产/步骤/预览行数 | 全部 0；库和预览为空 |
| 源 SHA-256、mtime、inode 前后 | 一致 |

[完整结果和审计](../evidence/mac-r1/result.json)、[源前](../evidence/mac-r1/source-before.json)、[源后](../evidence/mac-r1/source-after.json)。首次启动命令漏建会话工作目录，在 Node/Harness 启动和任何 API 请求前退出；补建目录后才启动真实会话，保留[启动错误](../evidence/mac-r1/launch-preparation-error.json)。失败后的只读汇总最初误将仅包含非 CETACEA 工具的 `ALLOWED` 当作全部集合，修正汇总口径后核对精确集合，没有改产品断言或增加请求，保留[修正说明](../evidence/mac-r1/evidence-summary-correction.json)。

失败后仅结束会话、汇总证据及撰写文档。证据已用非空环境变量进行密钥完整值匹配和常见前缀扫描，零命中，未记录密钥值。[扫描结果](../evidence/mac-r1/secret-scan.json)。后续诊断、重新运行和推送 `mac/R1` 等待用户决定。

## phase2-merged 合并后复验 — 2026-11-02（历史）

**结果：本轮请求范围内 PASS。** 在 Mac 上执行 `git fetch origin && git checkout phase2-merged`，被验收产品代码为 `08fcfd9b1070ddbed1569b01313cb71727134435`。本轮仅涉及验收脚本、证据、文档及瞬时 gate 文件忽略规则，没有修补产品代码、修改测试断言或启用 DeepSeek 实网请求。证据集中在 [evidence/mac-acceptance-merged](../evidence/mac-acceptance-merged/)。下文首次 `mac-validation` 及实体设备报告为历史记录，不能代替本轮结果。

| 请求项 | 结果 | 实测依据 |
|---|---|---|
| Python 3.13 venv 全量 pytest | PASS：**132 passed、2 skipped**，36.31 秒 | `.venv` 为 Python 3.13.18，editable 导入当前 checkout。运行 `.venv/bin/python -m pytest -q -rs --maxfail=1`；两个跳过均为需要 `DEEPSEEK_API_KEY` 和 `CETACEA_REALMODEL=1` 的实网模块。[日志](../evidence/mac-acceptance-merged/pytest-final.txt)、[退出码及命令](../evidence/mac-acceptance-merged/pytest-final-exit.json)、[环境](../evidence/mac-acceptance-merged/environment.json) |
| `photo_execute_import` 默认完整流程 | PASS，真实 Lightroom，`mock=false` | MCP SDK → 真实 CETACEA stdio server → 真实 0.26.0 Lightroom MCP。省略 `stages` 得到 ingest、lr_register、lr_preset、lr_export、preview_verify；一次 CLI 测试批准后一次执行，五阶段均 COMPLETED。公开 Nikon Z6 RAW 的曝光独立读回 **0.5**，实际 JPG 解码 **1600×1065**，`photo_verify_preview` 返回 OK。[计划](../evidence/mac-acceptance-merged/single-plan.json)、[MCP 请求/响应](../evidence/mac-acceptance-merged/single-mcp.jsonl)、[检查](../evidence/mac-acceptance-merged/single-checks.json)、[曝光读回](../evidence/mac-acceptance-merged/single-develop-readback.json) |
| 单张 Lightroom 租期 | PASS：仍为 **920 秒** | 实际执行路径的常量为 920；登记 metadata、预设、导出开始时，独立只读任务库采样的剩余时间分别为 **919.990、919.984、919.983 秒**。采样使用真实时钟，未改任务库租期。与核心赋值代码及 pytest 慢调用回归一起确认新流程未缩短租期。[真实调用及租期快照](../evidence/mac-acceptance-merged/single-real-calls.jsonl)。这是实际赋值/调用采样，不是持续 920 秒的真实 Lightroom 压测。 |
| 批准后改预设或导出设置 | PASS：均在工作前拒绝 | 两个全新真实适配器 home：计划并批准后，分别修改持久配置中的 `lightroom_name`、导出 `quality`。新的 MCP 请求均返回 `PERMISSION_DENIED: preset/export settings changed after approval`；任务仍 WAITING_APPROVAL、run_count=0，计划资产保持 PLANNED，无执行步骤、库文件、预览或真实 Lightroom 调用。[预设检查](../evidence/mac-acceptance-merged/tamper-preset-checks.json)、[导出检查](../evidence/mac-acceptance-merged/tamper-export-checks.json)、[零真实调用核对](../evidence/mac-acceptance-merged/final-inventory.json) |
| 中断后 `photo_retry_task`，不重新批准 | PASS：FAILED → COMPLETED，原批准保留 | 三张公开 RAW 测试副本已读回验证。第一张登记完成、第二张查询前，验收 gate 暂停；通过 UI 正常退出测试 Lightroom，确认进程退出后释放 gate。两个真实请求因插件断开失败，任务如实 FAILED（`lr_register: 2 failed`）。重开并核对同一个测试 catalog 后，由 MCP `photo_retry_task` 续跑，登记 **succeeded=2、skipped=1、failed=0**，随后三张预设、导出及 verify-preview 完成。原批准仍仅一条、摘要相同且未撤销，ingest 只完成一次，每张实际导入调用仅一次，库文件 SHA-256/mtime/inode 不变。[中断检查](../evidence/mac-acceptance-merged/interruption-before-retry-checks.json)、[退出确认](../evidence/mac-acceptance-merged/interruption-shutdown.json)、[重试检查](../evidence/mac-acceptance-merged/retry-resume-checks.json)、[最终清点](../evidence/mac-acceptance-merged/final-inventory.json) |

本轮隔离及证据说明：

- 使用独立测试 catalog `Cetacea-Phase1-Test-20261102.lrcat`，完整路径与下文历史环境一致。初始和恢复时均通过 UI 标题/URL 及 `lsof` 打开文件名确认；没有直接读取 `.lrcat` 内容。[单张守卫](../evidence/mac-acceptance-merged/single-catalog-guard.json)、[恢复守卫](../evidence/mac-acceptance-merged/retry-resume-catalog-guard.json)。
- 全新 home、源、库、预览位于本 checkout 的 `acceptance-data/mac-acceptance-merged/`（Git 忽略）。只使用下文署名来源的公开 Nikon Z6 样片副本：单张流程一份，中断流程三份；这是同一样片的四份测试副本。源在注册前创建，之后只读，SHA-256/mtime/inode 快照一致。未使用实体卡、客户数据、生产 catalog 或 NAS。
- 每个源在注册前另建 XMP/ACR 哨兵；全部拷贝资产目标哈希读回一致，最终库侧车路径集合和哈希与计划精确相同，没有新增未登记的 XMP/ACR。[独立最终检查](../evidence/mac-acceptance-merged/final-inventory.json)。哨兵验证字节和集合保留，不代表完整真实 XMP 内容兼容。RAW、JPG、catalog 和 token 不进入 Git。
- 测试批准由本轮用户授权的 CLI 操作端执行，批准摘要和命令保存于 `*-approval.json`；AI MCP 只有原有 14 个工具，没有获得批准入口。这里证明操作端批准与 AI 执行的边界，不声称用户逐次手工点击过批准 UI。
- 首轮 pytest 为 **120 passed、4 skipped**：额外两个模块因未安装 Harness 依赖整体跳过。[原始日志](../evidence/mac-acceptance-merged/pytest.txt)、[收集/跳过原因](../evidence/mac-acceptance-merged/collection.txt)。随后检出固定 Harness `ce7073d51254c26cd63b22a60835b8f948deb447`，按文档用 pnpm **11.28.5**、`--frozen-lockfile --ignore-scripts --filter '@deepseek-ai/dsh...'` 安装，再显式编译本机 flock addon，未执行其他生命周期脚本或全仓库构建。[安装日志](../evidence/mac-acceptance-merged/harness-install.txt)、[本机编译](../evidence/mac-acceptance-merged/harness-native-build.txt)。最终 pytest 子进程移除了模型凭据，未使用 DeepSeek key；`pip check` 通过。

复现辅助代码为 [run_acceptance.py](../evidence/mac-acceptance-merged/run_acceptance.py)、[mcp_capture_server.py](../evidence/mac-acceptance-merged/mcp_capture_server.py) 和 [final_inventory.py](../evidence/mac-acceptance-merged/final_inventory.py)。先确认上述测试 catalog，再依次运行 venv Python 的 `run_acceptance.py single`、`tamper-preset`、`tamper-export`、`interruption`、重开测试 Lightroom 后的 `retry-resume`，最后运行 `final_inventory.py`。`interruption` 需观察 `interruption-gate.ready.json`，正常关闭测试 Lightroom、确认进程退出后，才创建对应 release 文件。gate 明确属于验收控制，未注入错误响应、未伪造时钟或修改产品状态；真实调用/错误照常委托并记录。预设列表 probe 只记录 success/数量摘要，避免发布个人预设名称。脚本拒绝复用已有测试目录；复跑应先选择全新隔离目录和 gate 路径，保留旧证据。

本轮限制：没有意外产品验收失败；唯一任务 FAILED 是上述预先设计的断连场景，原错误和恢复记录均保留。中断点在照片之间，不能扩展为单次 catalog 写入时强杀、断电、操作系统崩溃或进程租期过期后的 PAUSED 实机验收。配置篡改验证的是工作台保存的预设选择及导出参数，未验证 Lightroom 内部同名/同 UUID 预设内容被外部修改的检测能力。旧的无 `lightroom` 快照兼容计划、其他 RAW/HE★ 类型、外置盘/Windows/大批量和真实 AI 模型决策均不在本轮结论内；DeepSeek 实网两个模块仍未运行。

## 首次 mac-validation 验收（历史记录）

本次照片处理与验收仅使用用户授权的测试数据和独立 catalog。未对客户照片、生产 NAS 或生产照片目录执行工作台任务，未向日常 catalog 发送照片查询、导入、预设或导出工具请求；不直接读取或修改任何 `.lrcat` 内容。Lightroom 自身通过 UI/插件管理测试 catalog。启动时曾显示日常 catalog，均先切换并确认独立测试 catalog 后才调用照片工具。

代码仓库：`https://github.com/wj3529805-netizen/my-harness-project`，分支 `mac-validation`，基线 `8abed3b62a1603d15b37d45b6a2d3b28797f4d2e`。GitHub clone 与压缩包基线一致。代码修复提交 `2956edc`。全部证据位于 [evidence/mac-acceptance](../evidence/mac-acceptance/)。

后续实体 SD/USB 卡及外置 APFS 补充验收见 [MACOS_DEVICE_VALIDATION.md](MACOS_DEVICE_VALIDATION.md)。下表为首次验收历史；后续全量回归已增至 100/100，A3 已补实体选中样本，A4 已补外置 APFS，exFAT/SMB 目标仍未通过实机验收。

## 环境和隔离边界

- macOS 27.0.1，arm64；Python 3.13.18，项目内 `.venv`；Node v26.12.1。
- 安装：`python3.13 -m venv .venv`，`.venv/bin/pip install -e '.[dev]'`。`pytest` 是 dev extra，单独 `-e .` 不保证安装它。系统 `python3` 为 3.9.6，未修改系统 Python。
- `mcp==2.3.0`；Lightroom MCP `@mskalski/lightroom-mcp@0.26.0`，用户 Modules 目录中的插件版本 0.26.0.0。npm 运行时安装在原压缩包工作目录的 `.lightroom-runtime`，没有全局 npm 安装。
- 实际代码与测试位置：`/Users/mac/Documents/ChatGPT/AI工作台/my-harness-project`。
- 所有有效 RAW 源、库、JPG、状态库在上述 checkout 的 `acceptance-data/`，已被 Git 忽略。
- 独立 catalog：`/Users/mac/Documents/ChatGPT/AI工作台/cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat`。通过 UI 标题、URL 和进程打开文件名确认身份；没有读取 catalog 内容。恢复/重启后重新确认，未向日常 catalog 发送照片操作。
- 测试预设为新建 `Cetacea Phase1 Test +0.50`，通过 Lightroom UI 导入；仅包含测试曝光调整。没有修改原有照片 XMP/ACR。
- CLI 测试操作端在本次用户授权范围内登记计划摘要并批准测试任务；没有把批准权限给 AI MCP。人类逐条点击批准的产品流程不在本次证据内。

## A1–A14 结果

| 条目 | 结果 | 实际证据与限制 |
|---|---|---|
| A1 | PASS | 原始项目在此 Mac 上 **71 passed**；修复和新增回归后 **98 passed**。[原始](../evidence/mac-acceptance/pytest-initial.txt)、[最终](../evidence/mac-acceptance/pytest-final.txt) |
| A2 | PASS | Mock 端到端在此 Mac 完成，源不变、哈希读回、重复执行、MOCK 标记均通过。[记录](../evidence/mac-acceptance/mock-e2e.txt)。原脚本固定 Linux banner 保留；它不能证明真实 Lightroom。 |
| A3 | PASS_LOCAL；实体卡 NOT_RUN | 公开 Nikon Z6 NEF 从测试文件夹扫描、计划、CLI 测试批准、导入；目标 SHA-256 读回一致；源 SHA-256/mtime/inode 不变。[检查](../evidence/mac-acceptance/cc0-register-checks.json)、[源快照](../evidence/mac-acceptance/source-before.json)。没有真实 SD 卡/读卡器接入。 |
| A4 | PARTIAL | 本机 APFS 导入/manifest/预览的硬链接发布实测通过。全局拒绝 os.link 的导入、清单、导出失败重试回归通过。未挂载外置 exFAT/SMB；尝试新建可丢弃 exFAT 镜像时操作系统拒绝，不能据故障注入宣称真实外置盘通过。 |
| A5 | PASS | 插件 UI 显示 Running true；实际 stdio 桥握手、只读请求及项目 `lightroom_get_status` 均成功、mock=false。[状态](../evidence/mac-acceptance/real-mcp-status.json)、[清单](../evidence/mac-acceptance/lightroom-tools.json)。适配器本身仍如实注明 catalog identity unverified；测试 catalog 身份由外部检查补证。 |
| A6 | PASS | 1 张公开 RAW 在独立 catalog 出现，并按确切库路径元数据读回；测试源/库 XMP、ACR 集合及哈希前后相同。[登记](../evidence/mac-acceptance/cc0-register-result.json)、[调用](../evidence/mac-acceptance/real-cc0-calls.jsonl)。 |
| A7 | PASS | 预设真实应用，曝光读回 **0 → 0.5**，数据库记录 preset_applied/testpreset。[前](../evidence/mac-acceptance/develop-before.json)、[后](../evidence/mac-acceptance/develop-after.json)。随后导出时 lr_status 更新为 EXPORTED。 |
| A8 | PASS | 每张 RAW 一张 JPG，实际解码尺寸 **1600×1065**，verify-preview=OK，mock=false。[检查](../evidence/mac-acceptance/real-preview-checks.json)。 |
| A9 | PASS | 删除这一张生成 JPG 后，verify-preview 精确返回对应 asset_id 的 missing，状态 FAILED；用先前保存的字节独占恢复后再次 OK，SHA-256 一致。[检查](../evidence/mac-acceptance/real-preview-checks.json)。 |
| A10 | PASS | CLI 重复计划/执行返回原任务且文件不变；实际 stdio MCP 15 次重复 plan/execute/import/preset/export 调用，任务、文件 inode/mtime/哈希和该任务 DB 行均不变。[MCP 证据](../evidence/mac-acceptance/A10-repeat-mcp-result.json)。最终 catalog 共 4 张测试照片，无重复。 |
| A11 | PASS | 独立临时 Mock home，实际项目 stdio MCP；14 个白名单工具，无批准、路径、shell、删除输入。批准/越界工具被拒，未批准各执行入口 NOT_APPROVED，批准行数 0，库/预览无文件，源不变，有 AI 审计。[证据](../evidence/mac-acceptance/mcp-boundary-clone.json)。 |
| A12 | PASS_BATCH_INTERRUPTION | 3 张测试 RAW 已拷贝；第一张登记完成、第二张尚未请求时关闭测试 Lightroom，后续请求失败，任务 FAILED 且只有第一张登记。重开同一测试 catalog 后 retry：**succeeded=2、skipped=1、failed=0**，catalog 该批次正好 3 张；源和库不变。[检查](../evidence/mac-acceptance/interruption-checks.json)。这是照片间的批次中断，不是单次 addPhoto 正在写 catalog 时的强制崩溃/断电。 |
| A13 | PASS_SAMPLE | 按固定 0.26.0 实际源码/schema 修适配器，并以真实 import/export/preset/metadata 响应及文件读回确认；单张逐目录导出成功。[调用](../evidence/mac-acceptance/real-cc0-calls.jsonl)。不宣称其他版本、所有机型和大批量兼容。 |
| A14（可选） | PASS_SDK；实际 AI 客户端 NOT_RUN | 本机 MCP SDK→真实项目 stdio 子进程连通，实际 list_tools 和拒绝测试通过；尚未改 Codex/Claude/Harness 全局配置或实际模型会话。[复现](../evidence/mac-acceptance/check_mcp_boundary.py)。 |

## 本次修复

1. `check_env.sh` 的 `$n` 后接中文括号在 macOS Bash 3.2 下触发未绑定变量；改为 `${n}`。检查优先使用本项目 venv，再找 Python 3.13；最低版本与项目声明统一。检查仍只读。
2. 真实适配器对齐 0.26.0：`source_path`、`preset_name/preset_uuid`、`width/height`。保留六工具白名单及 `on_existing=skip`，校验 success、complete、数量、照片确切路径/主片、预设身份、missing/失败项。先查询路径再导入，避免不确定结果重试时重复导入。
3. 状态从静态文字改为真实只读探测；嵌套 ExceptionGroup 展开到底层错误。import/export 工具超时与上游长操作对齐。
4. 照片、导入 manifest、预览 manifest 共用不覆盖发布回退；导出重试在无硬链接时复制并读回哈希，保留旧预览。修复 `state="FAILED"` 被 SQLite 当作列 `failed` 比较而从未复用成功预览的错误，改用绑定参数。
5. Lightroom 单资产租期从 300 秒扩到明确覆盖合法慢调用上限的 920 秒。回归证明活任务不会被 recover 夺走，第二执行者被拒，真正超时退出的任务仍可恢复。

原有测试未删除、未降低断言。新增测试涵盖真实契约失败、重试不重复、无硬链接全流程、目标冲突、慢调用租期；98/98 通过，`pip check` 和 `git diff --check` 通过。

## 失败和未完成事项

- 初次 pip 安装因沙箱 DNS 失败；在已授权安装范围内重试后成功。
- 原环境检查先报告系统 Python 3.9 太低，随后 Bash 变量解析中断；修复后全部检查通过。[最终环境检查](../evidence/mac-acceptance/check-env-final.txt)。
- 第一版合成 DNG 缺 NewSubfileType，Lightroom 拒绝：`canReadFile/dng_error_unsupported_raw`。导入任务正确 FAILED，库中已拷贝内容仍 VERIFIED，未伪报 Lightroom 成功。[失败](../evidence/mac-acceptance/real-first-result.json)。后续生成器诊断另留存；最终真实验收使用公开 NEF，不把合成样本的 macOS 解码等同于 Adobe 接受。
- 无硬链接 retry 新回归最初失败并揭示 SQLite 字符串问题；慢调用新回归在旧源码上也确实失败。修复后严格断言保留。
- 最终只读清点脚本最初误以为 search 摘要包含 path，触发 KeyError；状态请求和四张数量当时已成功，脚本随后改为按 ID 查询完整 metadata 再检查路径。原失败日志保留。
- Lightroom UI 控制曾连续超时；恢复测试会话并重新核对 catalog 后继续。A9 检查在受限沙箱内访问 bridge 锁被拒，停止该进程并在授权范围重跑成功。没有为此修改安全配置。
- 实体 SD/读卡器、外置 exFAT/SMB、真实 Windows、Nikon Z6 III HE/HE★、磁盘故障、断电、单张 catalog 写入中强杀、长期大批量运行均未验收。
- 无硬链接回退仍只协调遵守 `.cetacea-lock` 的写入者；不遵守锁的外部进程可能与 rename 竞争。此既有风险未消除。
- CLI 未批准执行仍会输出 NotApproved Python 堆栈；执行被正确拒绝。此用户已说明的体验问题未改。

## 测试样片来源与复现

公开样片 `Nikon-Z6.NEF`，25,994,889 bytes，SHA-256：`8ca94584578b35a422744c1a610174ce37df0691588edfdecaec3111b3fbbb02`，与发布方 [SHA256SUMS.txt](https://github.com/tellodaniel/revelraw-sample-raw-files/releases/download/v1/SHA256SUMS.txt) 一致。[发布来源](https://github.com/tellodaniel/revelraw-sample-raw-files)，对应 raw.pixls.us id 3581。

发布方 README 标注 CC0，但文件内嵌版权是 `(CC-BY-SA 4.0) Ludger Heide`，creator 为 Ludger Heide。本次保留署名和来源，未修改源文件，未把 RAW/JPG 放进 Git。目录/早期证据中的 `cc0` 是下载时采用的名称，不能消除许可证文字的差异；不要据此宣称已独立解决授权差异。这是 Nikon Z6 样片，不是 Z6 III HE/HE★。

验收脚本在 `evidence/mac-acceptance/`，有测试路径、导入源码位置及 catalog 打开文件名守卫，并对失败返回非零退出。真实操作脚本依赖本机已建立的独立 catalog、测试源和插件运行时，不应在生产 catalog 下运行。中断脚本的控制 gate 不入 Git。证据中的时间部分为 UTC（本地为 Asia/Shanghai）。测试工作目录保留，未清理测试照片或 catalog。
# AppleDouble follow-up (2026-11-03)

The R2 exFAT run failed when AppleDouble JPEG companions were counted as preview orphans. The fix recognizes regular `._` files by their AppleDouble magic, excludes them from source scans and output selection, and conservatively ignores regular files named exactly `.DS_Store` in output enumeration. Other `._` files are treated normally. Linux tests alone do not establish macOS or exFAT acceptance. Fix `fdfce5a` was subsequently re-verified on real ExFAT: the second rerun is **PASS_IN_SCOPE**, using MOCK Lightroom for filesystem checks and a separate real Lightroom smoke. See the R2 rerun section above; this remains a single-sample pass.

