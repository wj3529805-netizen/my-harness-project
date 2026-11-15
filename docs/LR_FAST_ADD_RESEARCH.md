# Lightroom 原地 Add：诊断与原型（2026-11-15）

结论：**SDK 原生导入触发器是当前主要候选；性能和“上次设置”来源仍待真实 TEST catalog 验证。**
已定位重复启动桥的调用层；约 120 秒的主要耗时仍未定位。
630 张 / 770 秒约为 1.22 秒/张，是用户提供的真实记录，本轮没有重新测量。
日志只证明 import 请求到下一次 metadata 请求之间约 119 秒，不能证明发生了超时。
本轮仅离线代码、MOCK MCP 与 Lua harness 验证；未启动、退出、连接或控制 Lightroom，
未访问照片盘、Adobe 用户目录或 catalog 内容。按项目禁止联网的规则，下面的官方来源
为 SDK/API 知识与后续复核入口，**本轮未联网逐页核验，也无本地完整 SDK 文档副本**。

## 路径审计与 120 秒假设

| 层 | 已确认的代码行为 | 不能据此断言的部分 |
| --- | --- | --- |
| 日常入口 | 外层每 100 张调用一次 `adapter.register(group)`，退出即关闭桥；7 批有 7 次进程初始化/关闭和 socket 重绑机会 | 每次重绑究竟耗时多少 |
| 适配器 | 一次 `register()` 内本来复用会话；日常构造器 `backoff_schedule=[]`、无 activation hook | Workbench 的默认退避不能解释这次日常运行 |
| 等待 | Python import 的 `read_timeout_seconds=310`，metadata 为 30；没有正常路径固定 sleep | 310 是等待上限，不能推出实际等待了 120 秒 |
| 桥补丁 | preparer 将 `import_photos_batch` 加入 JS 的 `LONG_RUNNING_TIMEOUT_MS` 映射，并加入 Lua dispatcher 的 long-running action 集合 | 本克隆没有 `.lightroom-runtime`；无法核实上游常量值、`actionTimeoutsMs`、dispatcher 内部超时、延迟重发或回复丢失 |
| Lua | 写锁外逐路径文件检查 / `findPhotoByPath`；缺失项仅一个 `withWriteAccessDo`，逐项 `addPhoto`；最后返回结果表 | 无计时时不能区分查询、RAW 解码、锁等待、事务提交或发送回复 |
| 读回 | 每批在 import 调用返回后执行 `get_photo_metadata`；必须收到并校验 import 结果映射，才能走正常读回 | 当前日常配置超时会失败停止，**没有“超时后靠读回算成功”路径**；适配器非日常重试路径才有 reconcile |

Lua 返回表应由上游 dispatcher 序列化并经 socket 回桥，再完成 MCP 调用；本地 preparer
仅注册 handler，并未改变这条回复链。不能假定后台任务已经取消，也不能因为下一条 metadata
请求出现就认定 add 循环耗时为整段间隔。编排者须在实际运行时核对
`dist/index.js` 的默认/长期 timeout、`actionTimeoutsMs` 和
`LightroomMCP.lrplugin/PluginInfoProvider.lua` 的长任务调度/响应/超时处理，保留其摘要。
目前没有证据支持通过调低超时、加 sleep 或盲重试来提速。

## 计时与解释

`--profile` 才向 handler 传 `profile: true`。Lua 使用 SDK `LrDate.currentTime()` 的秒值
乘 1000；它是墙钟时间，可覆盖 yield/I/O，`os.clock()` 是 CPU 时间，不适合本问题。
系统校时可能影响 Lua 墙钟差值；Python 使用单调 `time.perf_counter()`。
每批返回 `timing`：`total_ms`、`precheck_ms`、`write_txn_ms`（含锁获取和提交）、
`write_body_ms`、`add_ms`（实际尝试 add 的每项，含失败；已存在/取消项没有 add 样本）。
默认不返回 timing；启用计时不新增 catalog 查询或任何照片写操作。

JSON `profile.events` 保存：

- `bridge_spawn_initialize`：stdio 子进程启动和 MCP initialize。**不是 LR socket 就绪的独立证明**；延迟连接仍可能计入首次工具调用。
- `tool_call`：工具名、数量、耗时、错误类及白名单 Lua 数值；不复制任意错误 payload。import 最长等待 310 秒，metadata 30 秒。
- `readback` / `final_readback`、`bridge_close`；批次 `wall_ms` 与总 `wall_seconds`。

这些是嵌套区间，不可全部相加。baseline 批次 wall 含初始化、登记、读回和关闭；fast 批次
wall 含守卫和 import，末尾读回/关闭单列。总 wall 含扫描、守卫和报告 checkpoint，
最终 JSON 落盘本身不计入；`seconds_per_photo` 分母为计划输入总数，失败运行不是吞吐成功证据。

判断顺序：`sum(add_ms)` 是否接近事务耗时；`write_txn_ms - write_body_ms` 是否很大；
`precheck_ms` 是否很大；工具耗时减 Lua total 是否很大；最后比较启动、读回和关闭。
Python 与 Lua 时钟不对齐，只能比较区间长度。若 import 在约 120 秒报错而 Lua 无 timing，
须对照 LR 日志的事务完成/回复时间判断 timeout/传输问题，不能凭 cadence 定性。

## 可选快速路径

`register_import_to_lr.py --fast` / `bench_lr_add.py --mode fast`：
整次一个桥会话，1–200 张一批，每批写前守卫，只在最后按最多 100 张/调用统一读回。
它可能减少启动次数；630 张、100 张批次的 metadata 调用仍为 7 次，但集中在末尾；
小批次运行的 metadata 调用数才会明显下降。没有宣称读回完全消失。
每批确认响应只作为暂存结果，读回成功之前 JSON 仍为 pending / awaiting_readback。
部分失败即停止后续批次；断连不自动重试、不重启 LR；未读回路径保守记 failed/未确认，
未尝试批次记 pending。恢复后重跑先查存在，保持幂等。
末尾守卫失败或任一读回块错误会使整次暂存结果不能确认为成功。

仍保留逐路径 `findPhotoByPath`，未引入全库扫描。若 precheck 实测占主导，再比较
“每批逐路径查询”与“在写锁外一次 `getAllPhotos` 或已登记 folder 查询，批量读取 path 建索引”；
在小测试库及接近生产规模的测试库分别测查询时间、内存、首次/重跑和并行导入竞态。
大库全扫描可能更慢；缓存还会过期，不应在没有证据时替换精确身份检查。

暂不增加 1000 张 action。只有事务外/提交成本明显主导时才值得试验；更长事务增加 catalog
持锁时间、取消延迟及超时后状态不明的范围。先比较 batch 100 与 200。
Python 没有并行 add；LR 写访问串行化，多个 `LrTasks.startAsyncTask` 不能绕开写锁。

## 原生 Add 与替代路径

| 方法 | 判断与依据 | 建议 |
| --- | --- | --- |
| SDK `LrCatalog:addPhoto` | 要求写访问；按路径登记并返回 photo。不是原生 Import session API。内部必须识别文件/元数据，但 SDK 不承诺各内部阶段耗时或与 GUI Add 相同的调度。预览的具体后台行为及 NEF 解码成本须实测；本代码没有请求 render、develop 或 metadata 写入 | 先用分层计时证实热点；不能承诺禁用 LR 内部预览工作 |
| `LrTasks` 异步 | 可让可 yield 的 SDK 调用在异步任务中执行；上游已把本 action 注册为长期任务。异步保证可调度，不保证 add 更快 | 保留现有 dispatcher 语义 |
| (b′) `catalog:triggerImportFromPathWithPreviousSettings(path)` | 编排者新提供的 SDK 4.0 起 API：绕过对话框、沿用上次导入设置、异步返回，走原生 import engine。纠正此前“SDK 没有原生导入执行 API”的结论 | **主要候选**；仅显式 opt-in，先核对 Add 与全部设置，再触发并轮询；速度未实测 |
| 原生 Import → Add / `catalog:triggerImportUI(path)` | `triggerImportUI` 预选文件夹并打开原生对话框，由人核对后点 Import | `--ui` 半人工回退；人工原生 Add 仍作为速度基准 |
| Auto Import | watched folder 文件会移入配置 destination，再登记；要求的不是原地 Add，不能把 watched folder 与 destination 同址当作受支持技巧 | 不适合现有 USB 文件布局 |
| folder 启动参数 / 拖文件夹到 LR | 是否打开 Import 对话框受版本和操作系统影响，仍需 GUI 确认；不是可依赖的无界面 Add API | 仅人工评估；本轮未尝试 |
| Synchronize Folder | 对 catalog 已有文件夹扫描新增文件，可原地导入；对话框还可能提供移除缺失项/读元数据选项。公开 SDK 未知有对应执行方法 | 人工比较速度；保持 add-only 选项，不自动点击 |
| 键盘/GUI 脚本 | 焦点、语言、对话框和版本容易漂移；Plug-in Manager 不用于触发照片导入 | 不实现 |
| 直接 SQLite / `.lrcat` 写入 | 项目明确禁止；绕过 LR 事务和内部一致性，有损坏风险 | 拒绝；甚至不打开 catalog 内容 |
| Adobe CLI | 已知公开 Lightroom Classic 工具未提供受支持的无界面 catalog Add CLI；Lightroom 云 API 不是 Classic 本地 catalog API | 不依赖不存在的官方 CLI；未来需重新核实 |

参考来源（官方入口，未联网核验；API 细节以编排者实际 SDK 版本为准）：

- [Adobe Lightroom Classic developer / SDK](https://developer.adobe.com/lightroom-classic/)：SDK Guide 的异步任务/访问控制；API Reference 的 `LrCatalog.addPhoto`、`findPhotoByPath`、`getAllPhotos`、`withWriteAccessDo`、`LrDate.currentTime`、`LrTasks`、`LrApplication`。
- [Classic SDK API reference / LrCatalog](https://lrc.mcor.dev/modules/LrCatalog.html)：编排者提供的参考镜像，新增 `triggerImportFromPathWithPreviousSettings` / `triggerImportUI` 依据；本轮遵守禁止联网约束，未联网复核，真实 SDK 版本/调用语义仍须编排者核验。
- [Adobe：导入照片与视频](https://helpx.adobe.com/lightroom-classic/help/import-photos-video-catalog.html)：Copy / Move / Add 和导入选项。
- [Adobe：自动导入](https://helpx.adobe.com/lightroom-classic/help/import-photos-automatically.html)：watched folder 与 destination 的移动流程。
- [Adobe：管理文件夹](https://helpx.adobe.com/lightroom-classic/help/create-folders.html)：Synchronize Folder。
- 本仓可审计实现：[适配器](../src/cetacea/lightroom/real_mcp.py)、[日常入口](../scripts/mac/register_import_to_lr.py)、[Lua](../integrations/lightroom/HandlerCetaceaBatch.lua)、[固定版本桥补丁](../scripts/mac/prepare_lightroom_batch.py)。

## 编排者测速表与方法

优先比较 baseline/profile、fast/profile 和 native；每个“新增速度”样本须使用人工准备、内容相同的
独立空测试 catalog 和同一已导入照片目录。对同一个已登记 catalog 重跑只测 existing，
不能用作第二种模式的新增加速比。明确 OS、LR 版本、NEF 压缩类型、盘型、预览设置、
后台任务、冷/热缓存；避免并行导入。人工原生 Add 也使用独立空测试 catalog。
bench 默认 dry-run，拒绝 `~/Pictures/Lightroom` 整个目录（含大小写变体、子目录和符号链接父路径），
每批写前通过既有 `catalog_guard` 的 pgrep/lsof 精确核对当前仅打开指定 catalog，不读取 `.lrcat`。
测试 catalog 路径必须放在此保护目录以外；bench 无法仅凭目录名证明其它位置就是测试库。

| 场景 | N / batch | wall s / s每张 | spawn/init / close ms | import调用 ms | Lua precheck / txn / body / sum add ms | readback ms | added/existing/failed/pending |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 用户历史 baseline（无 profile） | 630 / 100 | 770 / 1.22 | 未知 | 未知 | 未知 | 未知 | 用户日志，非本轮验证 |
| baseline / fresh TEST | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| fast / 100 / fresh TEST | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| fast / 200 / fresh TEST | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| fast / existing rerun | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| native trigger / fresh TEST | 待填 | 待填 | 待填 | 触发耗时待填 | SDK 内部不可见 | 轮询/末尾快照待填 | 待填 |
| native trigger / existing rerun | 待填 | 待填 | 待填 | 触发耗时待填 | SDK 内部不可见 | 轮询/末尾快照待填 | 待填 |
| 人工 native Add / fresh TEST | 待填 | 待填 | 不适用 | 不适用 | SDK 不可见 | 人工核对 | 待填 |

建议：用以上表格决定后续方向；若 `addPhoto` 本身占绝大部分，复用桥只能省外围成本。
native trigger 走原生引擎是本轮的新主要候选，不能据此宣传原型已达到原生速度。

## (b′) Native trigger 原型与设置守卫

入口为 [lr_native_add.py](../scripts/mac/lr_native_add.py)，bench 增加 `--mode native`。
默认 dry-run：只读偏好、扫描目录、写新报告，不连接桥，不检查/操作正在运行的 LR。
执行时 `--catalog` 必填，并在初始查询、每个查询块、触发前与末尾快照前复用
`catalog_guard`（pgrep/lsof，不打开 catalog 内容）。日常入口可显式指定生产 catalog，
bench 仍拒绝 `~/Pictures/Lightroom` 及其大小写变体/符号链接；其它位置是否 TEST 由操作员确认。
原型不启动/退出/激活 LR、不切库、不自动点击，也不修改照片或 sidecar。

每次从 `defaults export com.adobe.LightroomClassicCC7 -` 只读取得 plist，初始计划和触发前
各检查一次；不写偏好。要求以下键**明确存在且匹配**，缺失/未知类型一律拒绝：

| 键 | 要求 |
| --- | --- |
| `AgImport_importBehavior` | `refInPlace`（Add） |
| `AgImport_crSettingsID` / `AgImport_metadataPresetID` | `<none>` |
| `AgImport_keywords` | 空字符串 |
| `AgImport_renamingTokensOn` | 0 / false |
| `AgImport_Import_add_photos_to_collection` | 0 / false |
| `AgImport_doCopyToBackupFolder` | 0 / false |
| `AgImport_generateDNGProxies` | 0 / false |

**DNG 转换键 UNKNOWN / UNVERIFIED**：没有本地权威 SDK/偏好映射材料，不臆造键名。
因此 dry-run 和 execute 均要求 `--i-checked-import-settings`，表示操作员已在原生 Import
界面核对 Add、无 DNG 转换、无改名、无 develop/metadata preset、无关键词、无集合、无备份。
该标志不能越过任何已知危险键。`lastCopyBehavior=copyToLibrary` 可能只是旧 Copy 模式记忆，
不把它当作当前 Add 模式的证据或否决项。`suppressImportDialog` 也不作为安全设置依据。

编排者提供的真实机器偏好快照满足上述已知条件（包含 recursive=1、duplicate=0、preview=bthm），
**本轮没有重读真实偏好；SDK 所谓 previous settings 是否恰好来自这些键仍 UNVERIFIED**。
偏好缓存、LR 版本差异和“检查后、触发前”竞态无法用此原型消除；执行期间禁止其它导入或更改设置，
先用可丢弃 TEST catalog 和隔离照片副本确认源文件未动。原型不改写设置来强制 Add；
一旦设置不符就停止。不要在未确认映射前自动用于生产。

期望列表是目录内 RAW（包括 DNG），不包含隐藏文件/隐藏目录、AppleDouble `._*`、
`proof(s)` / `preview(s)` / 预览目录；与日常 RAW 选择规则一致，每次 1..2000 张。
原生文件夹导入不接受此排除列表：预检另扫整个目录，列出 JPG、其它照片/视频以及被排除目录内
可能被导入的文件；默认拒绝，只有 `--allow-extra` 才继续。导入扩展名集合采用保守超集，
可能多报；它不是所有未来 LR 格式的保证。隐藏候选也保守列出，AppleDouble 不计照片。
拒绝任何符号链接，避免 LR 遍历范围不明；`recursivelyScanFolders` 必须是已知 0/1，
关闭递归但期望 RAW 在子目录时拒绝。触发前递归设置发生变化也拒绝。
原型不能阻止扫描后文件夹内容变化；请使用静止、隔离的测试输入。

Lua 的 `native_add_folder` 和 `native_add_folder_ui` 同处现有 MIT handler，验证目录、
1..2000 个唯一绝对路径、目录包含关系、普通文件与允许扩展名。preparer 将动作登记到
上游 long-running dispatcher，由其 async task 调用；handler 以 `LrTasks.canYield()`
拒绝同步调用，且调用链没有 `withWriteAccessDo`。返回 `triggered=true`、SDK
`LrDate.currentTime()` 的 `started_at` 只表示触发器返回，**不表示导入完成**。
`--ui` 选择 `triggerImportUI`，人必须再次核对 Add/选项并点击 Import；轮询含人的等待时间。

Python 整次复用一个桥会话，每 `--poll-seconds` 秒（默认 2）按最多 500 路径调用
`catalog_paths_present`，在写锁外用 `findPhotoByPath` 精确比对路径。默认轮询上限
`--timeout-seconds 1800`；请求等待也受剩余轮询预算约束（单次桥工具上限 310 秒）。
超时不取消 LR 原生导入，不重发触发器；可能仍在后台运行，不能盲目并行重跑。
轮询前后各一次可选 folder snapshot 使用 `getAllPhotos()` 过滤目录路径，所以会扫描全库；
普通轮询只查期望路径。初始扫描不计入 `native_wall_seconds`，末尾扫描也不计；
总 `wall_seconds` / `seconds_per_photo` 包含扫描、守卫、会话、轮询与最终快照，
最终报告落盘不计入。超时后的最终快照和桥关闭可能使总耗时超出轮询预算。

报告区分初始存在、最终 present/missing、`newly_present`、`extra_catalog_paths`（目录下全部非期望
catalog 路径）、`extra_adds`（前后快照中非期望路径增量），列出缺失路径。
delta 不能证明全由本次触发添加；有其它同时导入时归因 UNVERIFIED。
SDK 没有在这里提供原生 session 完成句柄：成功只表示全部期望路径在 catalog 中，
预览、其它文件和后台任务仍可能继续。末尾快照也不是最终完整 extras 保证。
`--profile` 保留桥调用/会话耗时，无法看到原生引擎内部阶段。

按相同路径幂等重跑时 LR 原生导入跳过已登记路径；原型仍发起一次 native trigger 并查询，
报告将这些路径计为 `existing`。全已存在时 `native_seconds_per_new_photo=null`，
不能用作新增速度。`ignoreSuspectedDuplicates=1` 也可能排除尚未按该路径登记的文件，
因此可能超时，脚本不修改该设置。真实 LR 幂等/设置映射和性能仍待验证。

## 编排者命令（人工准备 TEST catalog 后运行，本轮未执行）

先人工准备三个独立空 TEST catalog、同一隔离照片副本目录，并手动打开相应 TEST catalog。
下面 native 示例固定使用 `/private/tmp/CetaceaNativeAddTest/CetaceaNativeAddTest.lrcat` 和
`/private/tmp/CetaceaNativeAddPhotos`；两个路径须由编排者事先准备，照片目录限预期 RAW。
既有 runtime 不覆盖：preparer 要求输出 `.lightroom-runtime/batch` 不存在；如已有旧 runtime，
另行保留旧产物后再准备，不自动清理。用已批准的本地 0.26.0 node_modules 执行 preparer，
再人工按 [LIGHTROOM_BATCH.md](LIGHTROOM_BATCH.md) 禁用原插件并启用 staged 替代插件；
manifest 须有 `native_contract=1`，不用 npx 下载。此步骤不由本轮脚本自动操作 LR。

```sh
cd /Users/mac/Documents/Codex/cetacea-lr-nativeadd-20261115

# 先在原生界面核对所有设置；该标志代表人工确认，不能代替核对。
.venv/bin/python scripts/mac/bench_lr_add.py \
  --mode native --profile \
  --catalog /private/tmp/CetaceaNativeAddTest/CetaceaNativeAddTest.lrcat \
  --folder /private/tmp/CetaceaNativeAddPhotos \
  --i-checked-import-settings --dry-run \
  --report /private/tmp/cetacea-native-plan-20261115.json

# 人工确认正在打开的是上述空 TEST catalog 后：
.venv/bin/python scripts/mac/bench_lr_add.py \
  --mode native --profile \
  --catalog /private/tmp/CetaceaNativeAddTest/CetaceaNativeAddTest.lrcat \
  --folder /private/tmp/CetaceaNativeAddPhotos \
  --i-checked-import-settings --execute \
  --poll-seconds 2 --timeout-seconds 1800 \
  --report /private/tmp/cetacea-native-execute-20261115.json
```

半人工回退：在独立空 TEST catalog 上用同一 execute 命令加 `--ui` 并更换 `--report`。
此时人核对原生对话框后点 Import。不要为比较速度在已登记 catalog 上直接切换模式。
报告拒绝覆盖；再次运行须使用新报告名。日常入口命令相同，把 bench 文件名改成
`lr_native_add.py` 并去掉 `--mode native`。
