# 实体卡与外置 APFS 验收补充 — 2026-11-02

本次延续 `mac-validation`，使用用户接入并批准用于测试的两张卡，各选 1 张 RAW。照片字节和 JPG 留在本地测试目录，不随 Git 提交。Git 证据仅保存所选路径/哈希、卷身份和缩减技术元数据；完整插件元数据响应在本地解析后才过滤写日志。卡始终作为应用层只读来源：`O_RDONLY | O_NOFOLLOW`；没有更改挂载模式、写入测试文件、改名、删除或 chmod 卡内内容。

## 设备和范围

| 角色 | 实际设备 / 文件系统 | 本次操作 |
|---|---|---|
| SD | 128GB，内置 Secure Digital 读卡器，exFAT，卷 UUID `82A91C0F-BF3C-3DE2-AF4E-DEDF705C8E8E` | 只读选择 `DCIM/142NZ6_3/DSC_6484.NEF` |
| USB 卡 | 256GB USB，exFAT，卷 UUID `7FBCB909-0145-3DD8-AD2C-56989C78F446` | 只读选择 `DCIM/140NZ6_3/DSC_8443.NEF` |
| 外置盘 | 2TB Cetacea Studio，APFS，卷 UUID `1465C0D1-29A6-4DA1-8E13-3AC474A4BB83` | 仅新建测试目录，库/预览/合成探针均在其中 |

外置测试根为 `/Volumes/Cetacea Studio/Cetacea-Workbench-Test-devices-20261102-220045`；SQLite home 和审计记录在 repo 的 `acceptance-data/devices-20261102-220045`，不在外置盘或卡上。

两卡卷名有尾随空格，且名称相同；测试使用准确挂载路径和卷 UUID 核对，没有只依赖名称。没有对包含数百张照片的整个 DCIM 目录递归哈希。使用 Workbench 已支持的 `scan_result`，只对选中的一个真实文件做有界预哈希，实际 CopyEngine 再直接从实体卡读取、写目标、目标读回校验。整卡递归扫描和整卡导入均未运行。这是验收脚本传入有界预扫描结果的做法，不是为 CLI/MCP 新增了单文件选择功能；设备验收 home 仍登记源的父目录，不应将它用于 AI 的 photo_scan_source 调用。

## 已完成结果

- **A3，实体来源通过（各 1 张）**：两卡→本机 APFS、两卡→外置 APFS 均完成批准后的导入。源文件 SHA-256、大小、mtime、同挂载会话 inode 前后相同，目标 SHA-256 读回一致。重复执行不改目标；同哈希既有目标被跳过，异哈希内容被拒绝，既有目标字节/inode/mtime 不变。
- **A4，外置 APFS 通过**：真实 `os.link`、文件 `fsync`、目录 `fsync`、`chmod` 成功。外置盘上的完整 Mock 流水线、两种 manifest、JPG 校验和导出部分失败后的重试均通过。重试只重导失败项，原成功预览不动。Mock 结果均保留明确标记，不代表真实 Lightroom。
- **exFAT 目标仍未验收**：两张 exFAT 卡只证明真实 exFAT 来源读取。外置盘实际是 APFS，不应当作 exFAT 目标。为避免写卡/格式化现有盘，尝试在外置测试目录创建独立 256MB exFAT 磁盘映像；新版 `diskutil image create blank` 返回 `LOCALIZED_STRING_UNAVAILABLE`，`hdiutil create` 返回操作不被允许。两次均未创建可挂载的 exFAT 测试卷，未改动现有分区；不能声称 exFAT/SMB 目标回退实机通过。
- **真实 Lightroom 选中样本通过**：仅把外置库中的两张已验证副本登记到原独立测试 catalog，应用专用 +0.50 测试预设，元数据曝光读回 0.5；每张导出一个可解码 JPG、最大边 1600，verify-preview=OK、mock=false。两张源 NEF 和外置副本的 SHA-256/mtime/inode 保持不变。[结果](../evidence/mac-acceptance/devices-20261102-220045/physical-lightroom-result.json)。压缩子类型仍未独立辨识。本次设备扩展没有对相邻 XMP/ACR 做前后集合/哈希验收，原有侧车结论只沿用此前公开测试样片的对应证据。
- **回归测试 100/100 通过**：[日志](../evidence/mac-acceptance/pytest-devices-final.txt)。新增的是 ENOTSUP 两条参数化路径；既有 98 条保留。

源样本哈希：

- SD：`570d50780edcb135b43ff098878b0067d67ec38883622ce9d031951bcb736ec1`，18,565,632 bytes。
- USB 卡：`afb3f92276e8a7083603aee53c92b0d0cad4e0b4e4791a0265423d7e4a75cfec`，17,783,296 bytes。

TIFF 标签确认两者机型均为 `NIKON Z6_3`，主 RAW SubIFD 为 6064×4040、14 bit、Compression 34713。未独立辨识 HE / HE★ 压缩子类型，不能据这些标签宣称每种变体都已覆盖。

## 本次发现和修复

macOS 的 `errno.ENOTSUP=45` 与 `errno.EOPNOTSUPP=102` 是不同值。原代码只捕获后者；照片/manifest 发布和预览恢复会在返回 ENOTSUP 的驱动上直接失败。两处回退集合现均加入 ENOTSUP，仍先硬链接、后独占锁回退，仍不覆盖目标。

保留失败历史：新增参数化回归后修复前 2 failed / 2 passed；仅修 copier 后 1 failed / 3 passed；两处修复后 4 passed；全套 100 passed。证据 [enotsup-regression.json](../evidence/mac-acceptance/enotsup-regression.json) 及相邻阶段日志。这里的 ENOTSUP/无硬链接结果是明确故障注入，不是来自本次 APFS 硬件；实际 APFS 的硬链接成功，冲突探针只产生预期 EEXIST=17。

外置盘曾在实际拷贝前掉线。第一次写前守卫发现挂载点和原测试目录消失而停止；没有创建本机替代 `/Volumes/Cetacea Studio` 路径。用户重新接线后，先重新核对相同卷 UUID，再继续。后续设备脚本在初始检查 UUID/文件系统/挂载点，并在 Python 文件变更前检查目标挂载和 st_dev。未主动断开任何设备做破坏式故障测试。

## 证据与限制

证据目录：[devices-20261102-220045](../evidence/mac-acceptance/devices-20261102-220045/)。其中 `apfs-probe-*` 是原始能力/errno，`apfs-ingest-*` 是两卡有界导入和冲突保护，`apfs-pipeline-*` / `apfs-retry-*` 是明确 Mock Lightroom 的真实文件系统流水线。`physical-to-local-apfs.json` 是实体卡到本机校验；`image-create*.json` 保留磁盘映像失败。

`run_selected_cards.py`、`run_device_filesystem.py` 是复现入口，配置在本机被 Git 忽略的 `acceptance-data/device-active.json`。每次 filesystem 脚本创建独立 invocation 目录，SQLite 保持本机。源不会被清理，外置测试文件也保留，尚未推出外置盘或两卡。

样本量限 2 个用户批准文件；未覆盖整卡吞吐、异常拔盘中断、掉电、Windows、SMB、原生 exFAT 外置目标，以及 HE/HE★ 逐子类型。硬链接回退仍有不遵守 CETACEA 锁的外部写入者可能竞争 rename 的既有局限，普通 fsync 证据也不等同于断电耐久保证。
