# R6：R3+LR 实机验收手册

R3+LR 已准备，尚未在 Mac 或真实 Lightroom 上运行，状态 **NOT_RUN**。R4+LR 已推迟，状态 **NOT_RUN**。只处理卡上 `DCIM/142NZ6_3` 的 9 个 NEF、9 个 JPG，允许额外最多 1 个精确命名的 `NC_FLLST.DAT`；其他任何多余文件、目录或符号链接均导致 `FAIL_STOPPED`，不列出或读取其他文件夹；源卡只读，不连接 NAS，不碰生产 catalog。

## 前置条件

- Lightroom Classic 已打开，且只打开测试 catalog：`<HOME>/Documents/ChatGPT/AI工作台/cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat`。不要直接打开或修改 `.lrcat` 文件。
- MCP bridge 插件运行，`<HOME>/.config/lightroom-mcp/token` 存在，预设 `Cetacea Phase1 Test +0.50` 存在；关闭模态对话框。运行时须由用户关注 Lightroom：首次向“Cetacea Studio”卷写入时，macOS 可能请求可移除卷或网络卷访问权限，需点击允许；相机不支持或需要更新 Camera Raw 的提示也需用户处理。
- 此前 USB 读卡器已更换为内置 SD 读卡器；本次使用测试卡与独立目标卷。Z6III HE/HE★ NEF 在该 Lightroom 版本导入或导出可能失败；若发生，这是需保留证据的真实发现。
- 在本机终端设置 UUID，不要提交或写入证据：

```sh
cd <REPO>
git checkout prep/R6-lightroom
export CETACEA_SOURCE_UUID='<CARD_UUID>'
```

## 预检与运行

每次使用全新输出目录。预检核对卷、文件数量和大小、唯一 Lightroom 进程及打开的 catalog、bridge 和预设，不读取卡上文件内容，也不建任务或复制：

```sh
.venv/bin/python scripts/mac/r6_lightroom.py --mode r3 --confirm-card-readonly --preflight-only --out <REPO>/evidence/mac-r6/preflight-NEW --lightroom-test-catalog-path '<HOME>/Documents/ChatGPT/AI工作台/cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat'
```

预检结果写入 `preflight.json` 的 `checks`，并复制到 `result.json` 的 `preflight_checks`。各项 `passed` 为布尔值；`skipped: true` 表示前置条件未通过，修复前置条件后重新预检。失败项汇总在 `result.json` 的 `failures` 和 `console.txt`，`failed_step` 标出首个失败项。`catalog-guard.json` 保留预检记录。mock 模式的 Lightroom 检查是模拟结果，不能作为实机验证。

- `card_mounted`：无法根据 UUID 解析卡挂载点；检查 UUID、读卡器和挂载状态。
- `target_volume_present`：目标卷未挂载或路径不存在；接上盘并确认 `--target-base`，脚本不会创建该路径。
- `target_on_different_device`：目标必须与卡位于不同设备；更换目标卷。
- `evidence_outside_card`：证据目录必须在卡外；修改 `--out`。
- `scope_listing_9nef_9jpg`：测试文件夹必须恰有 9 个 NEF 和 9 个 JPG，允许额外最多 1 个 `NC_FLLST.DAT`，按名字和大小写精确放行；其他任何多余文件、目录或符号链接仍 `FAIL_STOPPED`。预检 counts 包含 `nef`、`jpg` 和 `other`。
- `node_binary_exists`、`mcp_index_exists`：运行时文件缺失；分别使用 `--lightroom-node`、`--lightroom-mcp-index` 指定正确文件。
- `bridge_token_exists`：bridge token 不存在；配置并启动 bridge，检查 token 文件。预检只检查文件是否存在，不读取内容。
- `lightroom_single_process`：启动 Lightroom Classic 并确保只有一个进程。
- `catalog_guard_matches_test_catalog`：仅打开指定的测试 catalog，检查 `--lightroom-test-catalog-path`。
- `mcp_connected`：检查 Lightroom、bridge 是否运行以及 token 配置。
- `preset_found`：在 Lightroom 中创建所需预设或使用 `--preset-name` 指定现有预设。

MCP index 默认按顺序查找 `<REPO>/.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js`，然后查找 `<REPO 的同级目录>/cetacea-workbench/.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js`；都不存在时保留第一个路径并报告缺失。Node 默认仍为 `/opt/homebrew/bin/node`。

将上面命令中的 `<HOME>` 换成本机主目录。预检成功后，用新的目录运行：

```sh
.venv/bin/python scripts/mac/r6_lightroom.py --mode r3 --confirm-card-readonly --out <REPO>/evidence/mac-r6/r3-NEW --lightroom-test-catalog-path '<HOME>/Documents/ChatGPT/AI工作台/cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat'
```

脚本按预检清单计划全部文件（有 DAT 时 19 个，无 DAT 时 18 个）后打印一行，其中包含 task ID、plan digest 和完整批准命令。检查后在**另一个终端**进入 `<REPO>`，执行该行给出的命令（形式如下，使用实际打印出的 home、task ID 和 digest）：

```sh
.venv/bin/python -m cetacea.cli --home <PRINTED_HOME> approve <TASK_ID> <PLAN_DIGEST>
```

默认等待批准 1800 秒；超时会停止。批准后依次执行 ingest、登记 RAW、套预设、导出和预览校验。JPG 只入库，用于配对，不登记或导出。`NC_FLLST.DAT` 同样入库并在目标端重新读回、校验 SHA-256，但绝不发送到任何 `lr_*` 阶段。此前 R3 仅 ingest 的运行只筛选 `.nef` 入库；DAT 仅出现在源文件前后清点中，R6 是首次将其入库。不要由脚本或 AI 自行批准。

## 结果与失败处理

`PASS` 表示真实 Lightroom 的任务五阶段完成：有 DAT 时 19 个目标文件（无 DAT 时 18 个）重新读回且哈希与卡一致；9 个 RAW 登记、套预设和导出，独立读回曝光均为 0.5；9 个 1600 像素最大边的预览与 JPG 配对并独立校验通过；批准恰一条且未变化，卡前后清点一致，三次 catalog 检查通过。`result.json` 的 `other_never_in_lightroom` 检查 DAT 未进入 Lightroom、预览或配对，并检查三个 Lightroom 阶段各成功 9 个；各项检查及原因均见 `result.json`。`PASS_MOCK_NOT_REAL_LIGHTROOM` 只表示模拟排练，绝不是实机通过。`PREFLIGHT_OK` 只表示预检通过；`FAIL_STOPPED` 表示安全检查或执行前步骤停止；`FAIL` 表示执行或验收判据失败。

若缺少 UUID、证据目录位于已解析的卡内或无法创建证据目录，可能没有 `result.json`；请保存终端错误并检查 UUID 和输出目录。其他失败时保留输出目录及目标卷现场，查看 `result.json`、`console.txt`、数据库和阶段证据；处理权限、bridge、预设或 Lightroom 提示后，使用全新的输出目录重跑。不要手动改库文件或 catalog 来掩盖失败。证据在 `--out` 指定目录；预览图片留在目标卷，不要提交。提交证据前运行隐私检查，不提交 UUID、个人路径或 token。

## R4+LR（已推迟，未准备为可运行）

以下仅为产品代码的预期设计，**未实现、未测试**：ingest 失败阻断后续 `lr_*` 阶段；retry 复用同一次批准重跑 ingest，清理 `.part`，跳过已发布且哈希一致的文件；18 个全为 VERIFIED 后才登记 9 个 RAW、套预设、导出和 `preview_verify`。未来需断言拔卡后无 `lr_*` 步骤，catalog 探针中无库内文件及 `.part` 路径；重新插卡后挂载路径须相同，但 `st_dev` 可能变化。目前没有可运行的 R4+LR 拔卡、hold 或重试流程。

## 局限

仅一张卡、一个已更换的内置 SD 读卡器、一台 Mac 和测试 catalog；不覆盖生产 catalog、NAS、其他卡或读卡器、断电及自然拔卡。R4 的受控 hold 设计也不能代表自然拔卡。mock 不等于 Mac 验收；适配器自身的 catalog identity unverified 由外部 `lsof` guard 补充，不能证明其他环境安全。
