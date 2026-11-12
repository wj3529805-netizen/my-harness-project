# Lightroom 批量原地登记

`RealLightroomMcpAdapter.register(files, *, before_batch=None)` 使用本仓新增的
`import_photos_batch` API。默认每批 **100** 张，`batch_size` 可设为整数 **1–200**。
一次 `register()` 共用一个 stdio MCP 子进程和会话；只在瞬断后重建连接。
每批缺失照片的 `catalog:addPhoto` 在同一个 `withWriteAccessDo` 内完成，
然后用批量 `get_photo_metadata` 核对路径、非虚拟副本和 catalog ID。
上游 metadata 一次最多 100 项，因此 101–200 张批次需要两次读回。
这里的 catalog 存在核对不同于摄入的 SHA-256 字节验证；摄入验证要求未变。

批量 API 只添加指定的精确文件路径，不递归目录、不移动、不复制、不套预设、
不调整曝光、不导出、不修改已有 XMP/ACR。`copy_to` 和其它批量 API 参数均拒绝。
工作流会先读回库文件哈希，再把全部待登记 `VerifiedFile` 一次交给适配器；
登记后不会逐张调用 `status()` 的预设探测。

## 准备隔离的新桥与插件

原版 0.26.0 没有此 API。必须同时使用本仓补丁后的 Node 桥和 Lua 插件；
未安装时会明确失败，不降级到逐张登记。**本次开发没有加载插件或操作 Lightroom。**

在当前克隆根目录运行（只读复制已核验的本地 MIT 上游，不联网下载）：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-20261112/bin/python \
  scripts/mac/prepare_lightroom_batch.py \
  --source-node-modules /absolute/path/to/reviewed-node_modules
```

准备器检查 `@mskalski/lightroom-mcp@0.26.0`、MIT 声明及四个补丁目标的固定 SHA-256，
复制到当前工作树忽略目录 `.lightroom-runtime/batch`，保留上游 LICENSE。
拒绝覆盖已有副本，也不修改来源运行时或全局 Modules。已有补丁副本时，
再次运行会正常拒绝覆盖。版本化实现为
[`HandlerCetaceaBatch.lua`](../integrations/lightroom/HandlerCetaceaBatch.lua) 与
[`prepare_lightroom_batch.py`](../scripts/mac/prepare_lightroom_batch.py)，
上游版权见 [`UPSTREAM_LICENSE.txt`](../integrations/lightroom/UPSTREAM_LICENSE.txt)。

在你安排的测试时段，先在 Lightroom 的「增效工具管理器 / Plug-in Manager」停用原版
Lightroom MCP，再添加并启用下面的替换副本，必要时重新载入插件：

```text
<本工作树>/.lightroom-runtime/batch/node_modules/@mskalski/lightroom-mcp/LightroomMCP.lrplugin
```

它沿用上游插件标识、token 和本机端口，不能与原插件或其它桥进程同时争用连接。
不需要把补丁写入 `~/Library/.../Modules`。回退时停用替换副本并重新启用原插件即可。
测试前请手动打开专用测试 catalog，保持正式 catalog 关闭。

## Python 入口：只添加

沿用现有环境，**不要更改 `bridge_env()` 的 HOME 修复**：

```sh
export CETACEA_BRIDGE_HOME="$HOME"
export LIGHTROOM_MCP_TOOLSETS=develop
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
```

`CETACEA_BRIDGE_HOME` 让子进程找到已有桥 token；代码不读取或打印 token 内容。
请在普通登录终端设置为操作员真实 HOME，不要在 HOME 已隔离的 Harness 中重新取值。
`bridge_env()` 始终向子进程指定 `develop`（上游包含 core），不启用 masks/all。

在已有的本地验收脚本中，用摄入后已读回 SHA-256 的库文件构造 `verified_files`
（`list[cetacea.lightroom.VerifiedFile]`），将原适配器替换为：

```python
from pathlib import Path
from cetacea.lightroom import RealLightroomMcpAdapter
from scripts.mac.r6_lightroom import catalog_guard

TEST_CATALOG = "/你的测试目录/Cetacea-Phase1-Test-20261102.lrcat"

def guard():
    # 只读取进程/打开文件信息，不打开 .lrcat、不读取窗口标题。
    if not catalog_guard(TEST_CATALOG)["matches_expected"]:
        raise RuntimeError("Lightroom 未只打开指定测试 catalog；停止下一批")

adapter = RealLightroomMcpAdapter(
    command=[
        "/opt/homebrew/bin/node",
        str(Path.cwd() / ".lightroom-runtime/batch/node_modules/@mskalski/lightroom-mcp/dist/index.js"),
    ],
    batch_size=100,
)
results = adapter.register(verified_files, before_batch=guard)
failed_files = [f for f, result in zip(verified_files, results) if result.error]
for result in results:
    print(result.asset_id, result.status, result.error)
# 不调用 apply_preset()、export_jpeg() 或 status()。
```

`VerifiedFile(asset_id, abs_path, sha256, size)` 的 `abs_path` 必须是已验证的目标库文件，
不能用卡目录或另一个未验证的源目录替代。直接调用适配器的脚本负责先完成验证和 catalog
守卫；Workbench 已保留自己的哈希与批准门槛。适配器不主动读取窗口或切换 catalog。
现有 `catalog_guard` 使用 `pgrep` / `lsof`；窗口标题为空不影响判断，测试 catalog
的打开文件仍在时继续，发现正式 catalog 与测试 catalog 同时打开也拒绝。
锁文件本身可能残留，不能把残留锁文件当成当前进程打开 catalog 的证明。
`before_batch` 在每批及重试之前执行，异常会阻止后续批次。

Workbench 的 `lightroom` 配置使用相同 `command` 和可选 `batch_size: 100`。
创建任务时仅选 `stages=["ingest", "lr_register"]`，按现有流程批准后执行，
即可让工作流只摄入和登记；不要使用包含 `lr_preset` / `lr_export` 的完整计划。
不需要改 DeepSeek ledger 或接入照片像素 API。

## 适配器 / Workbench 的失败与续登

每个输入始终对应一个 `RegisterResult`，`status` 为 `added`、`existing` 或 `failed`。
`existing` 会保存照片引用并计为工作流 skipped；其它批次可以继续完成。
逐项 `error` 与任务步骤详情保留失败原因。排除故障后可调用
`adapter.register(failed_files, before_batch=guard)` 续登，或对已批准的失败工作流任务
使用 `Workbench.retry(task_id)`；已存 `lr_photo_id` 的资产会跳过。

如果导入已执行但回复丢失，重连后先批量查询全部原批次，只重试缺失路径。
无法得知是否本次新加入、但已确认存在的照片报告为 `existing`，不猜测 `added`。
重试耗尽或返回映射不完整时按资产报告失败，可安全重新提交；插件先查存在再添加。
安全回调失败会停止剩余登记，不作为网络错误重试。

## 日常流程：导片助手导入 → 一条命令登记

入口为 [`scripts/mac/register_import_to_lr.py`](../scripts/mac/register_import_to_lr.py)。
先让导片助手完成项目目录的导入及目的地 SHA-256 读回验证，再登记该项目中的照片。
此入口只扫描路径和文件属性，不读取照片内容、不重复导片助手的复制与哈希验证，
也不声称本次完成了字节验证；登记后的读回仅核对 catalog 中的路径和照片身份。
内部复用 `VerifiedFile` 作为路径载体，`sha256` 留空。
入口递归选择精确文件路径，不跟随符号链接，默认仅选 RAW。
默认排除的完整目录名为 `proof`、`proofs`、`preview`、`previews`、`预览`、`预览图`、`预览照片`
（不区分大小写）；不按部分名称匹配。
`--include jpg` 仅选 JPG/JPEG，`--include all` 同时选 RAW 和 JPG/JPEG。
多个项目可重复传入 `--folder`；用 `--exclude-dir` 追加要排除的单个目录名，
可重复使用，不能传目录路径。

首次使用当前克隆时，先准备本克隆的补丁桥。下面的来源参数应替换为操作员已准备并核验的
MIT `@mskalski/lightroom-mcp@0.26.0` 本地 `node_modules`，不要从其它项目复制业务代码：

```sh
.venv-20261112/bin/python scripts/mac/prepare_lightroom_batch.py \
  --source-node-modules /absolute/path/to/reviewed-node_modules
```

准备器只写本克隆的 `.lightroom-runtime/batch`，不会安装或重载插件；已有副本不能覆盖。
日常入口要求这份补丁桥，缺失时会提示运行准备器，不会联网安装或降级为逐张登记。
插件也必须是上述补丁版：在约定时段由操作员按前文步骤在 Lightroom 增效工具管理器中启用。
开发与自动化测试不启动、退出或控制 Lightroom，也不修改全局 Modules 或 LR 偏好。

操作员手动打开本次期望使用的测试或正式 catalog，确认只打开该 catalog。
在当前克隆的普通登录终端设置环境，然后先 dry-run（默认也是 dry-run）：

```sh
export CETACEA_BRIDGE_HOME="$HOME"
export LIGHTROOM_MCP_TOOLSETS=develop
mkdir -p "$PWD/acceptance-data"

.venv-20261112/bin/python scripts/mac/register_import_to_lr.py \
  --folder /absolute/path/to/imported-project \
  --catalog /absolute/path/to/Expected.lrcat \
  --include raw --batch-size 100 --dry-run \
  --report "$PWD/acceptance-data/daily-lr-dry-run.json"
```

确认选片范围后执行同一入口，加上 `--execute`，并使用新的报告文件：

```sh
.venv-20261112/bin/python scripts/mac/register_import_to_lr.py \
  --folder /absolute/path/to/imported-project \
  --catalog /absolute/path/to/Expected.lrcat \
  --include raw --batch-size 100 --execute \
  --report "$PWD/acceptance-data/daily-lr-execute.json"
```

`--catalog` 必须是期望已打开的 `.lrcat` 绝对路径。入口复用 `catalog_guard`，
执行时每批前核对 Lightroom 是否只打开它；不匹配即停止后续登记，不打开或切换 catalog。
dry-run 仅扫描并生成计划，不连接 Lightroom、不检查当前打开的 catalog，
不判定哪些路径为 `existing`，也不写任何登记批次。
入口只调用批量原地 add 与 catalog 路径读回，不复制、不移动、不套预设、不调曝光、不导出。
已有路径计为 `existing`，不重复添加。JSON 报告给出 `added` / `existing` / `failed`
计数、待处理 `pending` 计数及每批状态，终端同时显示中文摘要。
`--report` 为必填项，必须位于所有 `--folder` 目录之外，父目录须已存在。
报告以仅当前用户可读写的 `0600` 权限新建，已有文件不会覆盖。
报告属于本地运行结果，可能含项目路径，应保存在忽略的 `acceptance-data/` 中，
不提交到公开仓库。

日常入口在首个未完成批次后立即停止，不自动重试断连，也不会激活或重启 LR。
LR 或插件中途崩溃、断连时，运行失败并报告未完成批次；未收到确认的路径不能当作成功。
由操作员恢复 LR 和插件、重新确认同一个 catalog 后，直接重跑 `--execute` 命令即可续登，
仅更换 `--report` 文件名以保留前次结果。已写入的路径会记为 `existing`，剩余路径补齐；
无需改 ledger 或手工删除 catalog 条目。自动恢复测试使用明确标注的 fake MCP，
不代表已完成真实 LR 崩溃验收。

## 验证范围与风险

自动测试包括本地 MOCK stdio 的 PID 复用、批量/分批/读回、去重、部分失败续登、
瞬断与 MCP SDK 断连错误、HOME 桥、工作流租约/取消、catalog 守卫，以及实际执行 Lua
代码的 MOCK catalog 单写事务测试。没有执行真实 134 张登记或测量真实加速比。
没有修改正式 catalog、源卡、照片盘或其它工作树。

Lightroom SDK 的 `findPhotoByPath` 必须在写访问之外调用，因此插件先查存在，再在一个
事务中添加缺失项。若同时有 UI 或其它导入者添加相同路径，`addPhoto` 仍返回已有对象而
不重复添加，但 `added` / `existing` 的数量可能受这个时间窗口影响；测速期间请避免并行
导入或修改 catalog。连接超时也不证明 Lightroom 已取消当前事务，重试依靠存在核对去重。
事务按张数有界，耗时仍取决于 Lightroom / 文件格式；可调小批量以缩短持锁时间。

历史批量 API 开发 PR 要求（不适用于本次日常入口 PR）：以 `cursor/unpaired-photo-ingest-fec0` 为 base，仅推送
`codex/lr-batch-register`；不要把本次提交直接推到 PR #1 分支，不合并 PR。
本次日常入口 PR 使用 `codex/daily-import-lr-register-20261112`，base 为 `phase1`，不合并。
