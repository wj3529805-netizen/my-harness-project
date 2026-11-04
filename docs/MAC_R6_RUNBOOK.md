# R6：R3+LR 实机验收手册

R3+LR 已准备，尚未在 Mac 或真实 Lightroom 上运行，状态 **NOT_RUN**。R4+LR 已推迟，状态 **NOT_RUN**。只处理卡上 `DCIM/142NZ6_3` 的 9 个 NEF 和 9 个 JPG，不列出或读取其他文件夹；源卡只读，不连接 NAS，不碰生产 catalog。

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

将上面命令中的 `<HOME>` 换成本机主目录。预检成功后，用新的目录运行：

```sh
.venv/bin/python scripts/mac/r6_lightroom.py --mode r3 --confirm-card-readonly --out <REPO>/evidence/mac-r6/r3-NEW --lightroom-test-catalog-path '<HOME>/Documents/ChatGPT/AI工作台/cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat'
```

脚本计划全部 18 个文件后打印一行，其中包含 task ID、plan digest 和完整批准命令。检查后在**另一个终端**进入 `<REPO>`，执行该行给出的命令（形式如下，使用实际打印出的 home、task ID 和 digest）：

```sh
.venv/bin/python -m cetacea.cli --home <PRINTED_HOME> approve <TASK_ID> <PLAN_DIGEST>
```

默认等待批准 1800 秒；超时会停止。批准后依次执行 ingest、登记 RAW、套预设、导出和预览校验。JPG 只入库，用于配对，不登记或导出。不要由脚本或 AI 自行批准。

## 结果与失败处理

`PASS` 表示真实 Lightroom 的任务五阶段完成：18 个目标文件重新读回且哈希与卡一致；9 个 RAW 登记、套预设和导出，独立读回曝光均为 0.5；9 个 1600 像素最大边的预览与 JPG 配对并独立校验通过；批准恰一条且未变化，卡前后清点一致，三次 catalog 检查通过。各项检查及原因见 `result.json`。`PASS_MOCK_NOT_REAL_LIGHTROOM` 只表示模拟排练，绝不是实机通过。`PREFLIGHT_OK` 只表示预检通过；`FAIL_STOPPED` 表示安全检查或执行前步骤停止；`FAIL` 表示执行或验收判据失败。

若缺少 UUID、无法解析卡挂载点或无法创建证据目录，脚本会在确认输出位置不在卡上之前退出，此时可能没有 `result.json`；请保存终端错误，检查 UUID、挂载和输出目录。其他失败时保留输出目录及目标卷现场，查看 `result.json`、`console.txt`、数据库和阶段证据；处理权限、bridge、预设或 Lightroom 提示后，使用全新的输出目录重跑。不要手动改库文件或 catalog 来掩盖失败。证据在 `--out` 指定目录；预览图片留在目标卷，不要提交。提交证据前运行隐私检查，不提交 UUID、个人路径或 token。

## R4+LR（已推迟，未准备为可运行）

以下仅为产品代码的预期设计，**未实现、未测试**：ingest 失败阻断后续 `lr_*` 阶段；retry 复用同一次批准重跑 ingest，清理 `.part`，跳过已发布且哈希一致的文件；18 个全为 VERIFIED 后才登记 9 个 RAW、套预设、导出和 `preview_verify`。未来需断言拔卡后无 `lr_*` 步骤，catalog 探针中无库内文件及 `.part` 路径；重新插卡后挂载路径须相同，但 `st_dev` 可能变化。目前没有可运行的 R4+LR 拔卡、hold 或重试流程。

## 局限

仅一张卡、一个已更换的内置 SD 读卡器、一台 Mac 和测试 catalog；不覆盖生产 catalog、NAS、其他卡或读卡器、断电及自然拔卡。R4 的受控 hold 设计也不能代表自然拔卡。mock 不等于 Mac 验收；适配器自身的 catalog identity unverified 由外部 `lsof` guard 补充，不能证明其他环境安全。
