# macOS validation — 2026-11-02

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
