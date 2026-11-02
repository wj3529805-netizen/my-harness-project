# macOS（Apple Silicon / M4 Max）交接：安装、配置、验收、回滚

> **验证记录**：开发期 Linux Mock 结果不等于真实 Lightroom 验证。2026-11-02 已在 Apple Silicon Mac 上开展独立测试 catalog 验收；逐项结果、失败历史和硬件限制见 [MACOS_VALIDATION.md](MACOS_VALIDATION.md)。下面未勾选清单保留为操作模板，不代表最新结果。

## 0. 先决条件
- macOS，Apple Silicon（arm64），Python ≥ 3.13（与 pyproject.toml 一致），Node ≥ 20（lightroom-mcp）；若要跑 deepseek-harness 需 Node ≥ 24.9。
- Lightroom Classic 已安装（本项目不碰 .lrcat，也不要求关闭，但**验收请使用一个独立的测试目录和测试 catalog，不要用生产 catalog**）。
- 只读环境检查：`bash scripts/mac/check_env.sh`（不安装、不修改任何东西）。

## 1. 安装 CETACEA 工作台（项目内 venv，不做系统级安装）
```bash
cd cetacea-workbench
python3.13 -m venv .venv              # 系统 python3 可能仍为 3.9
.venv/bin/pip install -e '.[dev]'     # 依赖：mcp、pillow；dev 包含 pytest
.venv/bin/python -m pytest -q         # 在 Mac 上先复跑全部自动化测试
.venv/bin/cetacea init --home ~/cetacea-test/home --library ~/cetacea-test/library --preview ~/cetacea-test/preview
```
library / preview 目录请放在**测试路径**，不是生产照片目录、也不是生产 NAS。

## 2. 先用 Mock 跑通（Mac 上）
```bash
.venv/bin/python scripts/e2e_demo.py --out /tmp/cetacea-e2e-mac
```
确认报告里全部带 MOCK 标记，且通过。

## 3. 接入真实 Lightroom（需要用户手工确认每一步）
1. 打印配置（不写入）：`bash scripts/mac/print_lightroom_mcp_config.sh`
2. 安装 Lightroom 插件（任选其一，来自上游 README，均为第三方代码，请先自行审阅）：
   - `npx -y @mskalski/lightroom-mcp@0.26.0 install-plugin`（插件装到 `~/Library/Application Support/Adobe/Lightroom/Modules/`）；或
   - 手动下载 release 中的 `LightroomMCP-macos.lrplugin.zip`，解压后把 `LightroomMCP.lrplugin` 放入上述 Modules 目录。
3. 重启 Lightroom Classic → 文件 → 增效工具管理器 → Lightroom MCP → **Start Server**。
4. 在 CETACEA 配置中设置 `lightroom.adapter = "real_mcp"`，`LIGHTROOM_MCP_TOOLSETS=develop`（**不要用 `all`**）。
5. CETACEA 的真实适配器只允许调用：`import_photos`、`get_photo_metadata`、`apply_develop_preset`、`export_photos`、`list_develop_presets`、`search_photos`；不会调用删除/重置/覆盖导出类工具；不使用模拟鼠标键盘；不直接读写 .lrcat。
6. 在 Lightroom 中预先手工准备一个**测试预设**，用 `cetacea preset add` 登记。

## 4. 验收清单模板（实际结果见 MACOS_VALIDATION.md）
- [ ] A1 `pytest` 在 Mac 上全绿。
- [ ] A2 Mock 端到端在 Mac 上通过。
- [ ] A3 读卡器/真实 SD 卡（**只读**，建议先拷一份测试 RAW 到 ~/cetacea-test/card）：扫描、计划、人工批准、导入，目标文件 SHA-256 与源一致；源目录字节与 mtime 不变。
- [ ] A4 APFS 上硬链接提交路径可用（`os.link`）；外置 exFAT/SMB 盘上走回退路径并通过（回退使用 `.cetacea-lock`，见 KNOWN_RISKS）。
- [ ] A5 Lightroom 插件可启动；`lightroom_get_status` 显示真实（非 MOCK）状态。
- [ ] A6 导入 1 张测试 RAW 到测试 catalog：照片出现在 catalog；CETACEA 不产生 XMP/ACR 修改（对比前后 `*.xmp`、`*.acr` 的哈希）。
- [ ] A7 应用测试预设：照片确实应用；`lr_status` 记录。
- [ ] A8 导出预览 JPG：每张一个，尺寸/可解码；`verify-preview` 状态 OK。
- [ ] A9 故意删除一张预览 JPG → `verify-preview` 精确报告 missing，状态非 OK。
- [ ] A10 重复提交同一任务/重复调用 AI 工具：不重复拷贝、不重复导入。
- [ ] A11 AI（MCP）无法批准任务；未批准任务不会拷贝任何文件。
- [ ] A12 Lightroom 在导入中途被关闭：任务进入 FAILED/PAUSED，重试后只补处理未完成的，不重复。
- [ ] A13 `lightroom-mcp` 的 `import_photos` / `export_photos` 实际返回格式与适配器假设一致（适配器按“库内文件路径”映射照片、每次导出 1 张到全新空目录）；如不一致，修适配器并补测试——这是最大的接口风险。
- [ ] A14 （可选）Harness / Codex / Claude Code 通过 `cetacea mcp-serve` 连入，仅看到白名单工具（无路径、shell、删除、批准工具）。

## 5. 回滚计划
- CETACEA 对源目录只读，从不删除卡内文件；回滚**不需要**恢复源数据。
- 库目录：本项目只新增文件，不覆盖。回滚 = 手工删除测试库目录 `~/cetacea-test/library/<order>/<photographer>/<batch>`（人工操作，CETACEA 没有删除功能）。
- 预览：`preview/…/run-N` 为独立目录，直接删除即可。
- 状态：`~/cetacea-test/home/state.sqlite3`（含审计日志）删掉即重置；建议先备份留证。
- Lightroom：测试 catalog 里导入的照片用 Lightroom 自带“从目录中移除”手工处理；CETACEA 不会也不被允许调用移除工具。
- 插件：在 Lightroom 增效工具管理器停用并删除 `~/Library/Application Support/Adobe/Lightroom/Modules/LightroomMCP.lrplugin`。
- 配置：把 `lightroom.adapter` 改回 `mock` 即停止一切对 Lightroom 的调用。

## 6. Windows
未开发、未验证。路径安全与硬链接逻辑含 POSIX 专用调用（O_NOFOLLOW、os.link 语义），移植到 Windows 需要单独评估。
