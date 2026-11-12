# R1–R5 最终验收摘要

截至 2026-11-03，以下结论只适用于实际执行的范围；保留失败和未覆盖项。背景与操作细节见 [macOS 验证记录](MACOS_VALIDATION.md) 和 [R3/R4 操作说明](MAC_R3_R4_RUNBOOK.md)。

| 项目 | 实际执行范围 | 结果 | 证据 | 局限 |
| --- | --- | --- | --- | --- |
| R1 | 授权重跑真实 AI 会话：DeepSeek、受限 Harness、真实 Lightroom，单张公开样片及测试 catalog | PASS_IN_SCOPE；首次运行 FAIL，保留历史 | [重跑](../evidence/mac-r1/retry-1/result.json)、[首次](../evidence/mac-r1/result.json) | 有限样本；首次传输失败根因未确定 |
| R2 | exFAT SD 目标；文件系统检查使用 MOCK Lightroom，另做真实 Lightroom 冒烟 | 原运行因 AppleDouble 被误判 orphan 而 FAIL_STOPPED；修复 `fdfce5a` 后 rerun2 单样本 PASS_IN_SCOPE | [原结果](../evidence/mac-r2/result.json)、[重跑结果](../evidence/mac-r2-rerun2/result.json)、[验证记录](MACOS_VALIDATION.md) | MOCK 故障与重试检查和独立真实 Lightroom 冒烟各自有效，不能互相替代；首次重跑的验收脚本解析失败亦保留 |
| R3 193556 | 测试文件夹，45 张 HE★，仅 ingest | PARTIAL_NOT_COVERED | [结果](../evidence/mac-r3/run-20261103-193556/result.json)、[类型](../evidence/mac-r3/run-20261103-193556/subtype-report.json)、[计时](../evidence/mac-r3/run-20261103-193556/timing.json) | 未覆盖 HE；速度不可用 |
| R3 202435 | 测试文件夹，55 张 HE★，仅 ingest，冷读约 97 MB/s | PARTIAL_NOT_COVERED | [结果](../evidence/mac-r3/run-20261103-202435/result.json)、[类型](../evidence/mac-r3/run-20261103-202435/subtype-report.json)、[计时](../evidence/mac-r3/run-20261103-202435/timing.json) | 未覆盖 HE；单次冷读 |
| R3 214716 | 测试文件夹，7 张 HE★、1 张 HE、1 张 LOSSLESS，仅 ingest | PASS | [结果](../evidence/mac-r3/run-20261103-214716/result.json)、[类型](../evidence/mac-r3/run-20261103-214716/subtype-report.json)、[读回](../evidence/mac-r3/run-20261103-214716/readback.json)、[计时](../evidence/mac-r3/run-20261103-214716/timing.json) | 单次、单文件夹；速度不可用 |
| R3 other-card-20261106-005829 | 另一张卡 + USB 读卡器，DCIM/142NZ6_3，`--max-files 12`，仅 ingest；Protocol=USB | PASS | [结果](../evidence/mac-r3/run-other-card-20261106-005829/result.json)、[类型](../evidence/mac-r3/run-other-card-20261106-005829/subtype-report.json)、[读回](../evidence/mac-r3/run-other-card-20261106-005829/readback.json)、[说明](../evidence/mac-r3/NOTES-other-card-20261106.md) | 路径证明；571 MB/s 为热缓存不可作速度证据；与内置 SD 并行挂载时靠 UUID 区分 |
| R4 202626 | 拔卡尝试 | INTERRUPTION_NOT_ACHIEVED | [结果](../evidence/mac-r4/run-20261103-202626/result.json) | 观察到进度前复制已完成 |
| R4 203649 | 限速拔卡尝试 | FAIL_STOPPED | [结果](../evidence/mac-r4/run-20261103-203649/result.json) | 观察到拔卡前子进程退出 |
| R4 205826 | 人为限速、文件中途暂停后拔卡及恢复 | PASS | [结果](../evidence/mac-r4/run-20261103-205826/result.json) | 拔卡时 part 大小记录为 0；后续使用更严格判据 |
| R4 215049 | 仅拔卡前清点 | 未完成，无结果 | [清点](../evidence/mac-r4/run-20261103-215049/pre-inventory.json) | 不计作运行通过 |
| R4 215121 | 人为限速、文件中途暂停后拔卡及恢复 | PASS，更严格判据：拔卡时 held part 存在，首个失败为该文件的 EIO | [结果](../evidence/mac-r4/run-20261103-215121/result.json)、[说明](../evidence/mac-r4/run-20261103-215121/README.md) | 受控暂停场景，见下文 |
| R5 | 替换样片、对当前树事后脱敏 | 已在 `prep/R5` 执行 | [说明](../evidence/mac-r5/README.md)、[映射](../evidence/mac-r5/desensitization-map.json)、[样片](../samples/README.md) | 仓库公开；Git 历史未重写 |

R3 214716 的 HE 帧是 DSC_9725.NEF；其[清点](../evidence/mac-r3/run-20261103-214716/inventory-before.json)与目的地读回 SHA-256 均为 `d77f05b50d569de25ce56c435bf7c8d3b40abc250d0a3acee4c376645e941f7e`，与 [samples/Nikon-Z6III-HE-DSC_9725.NEF](../samples/README.md) 所记哈希一致。

## R6：真实 Lightroom 下的 R3/R4

截至 2026-11-03 的原验收记录：R3+LR 已准备，尚未在 Mac 运行，状态 **NOT_RUN**；R4+LR 已推迟，状态 **NOT_RUN**。见 [R6 手册](MAC_R6_RUNBOOK.md)。2026-11-12 日常范围的更新见下一节。

## 2026-11-12 日常可用验收

日常入口与操作步骤见 [日常流程：导片助手导入 → 一条命令登记](LIGHTROOM_BATCH.md#日常流程导片助手导入--一条命令登记)。
以下真实 LR 历史来自晶确认的 2026-11-10 正式登记结果；本次开发未重新访问正式 catalog，
未启动、退出或操作 Lightroom，未修改 LR Modules、偏好或现有 XMP/ACR。

| 项目 | 结果 | 验收范围与限制 |
| --- | --- | --- |
| R6 真实 LR 批量登记 | PASS（2026-11-10 已完成） | 在正式 catalog 完成 2 个客户项目，共 755 张 RAW 全部登记、无重复；仅添加精确路径，不披露客户名或客户目录 |
| R6 中途崩溃恢复：自动化 | **PASS（fake MCP）** | 30 张、每批 10 张；第 2 批写入 4 张后 fake MCP 进程强退，首次失败记录未完成批；重跑为 14 existing + 16 added，最终 30 张各一条、无重复。此项仅代表自动化模拟 |
| R6 中途崩溃恢复：真实 LR | **SKIPPED** | 晶正在使用 LR，需另约时段在隔离测试 catalog 跑 |
| SMB/NAS 目标 | **PASS（工具流程） / 附加时间戳检查 FAIL、待查** | 在授权目录 `CETACEA-SMB-Test-20261112` 完成全量、重复、中途取消与续导，计数及时间戳局限见下表 |
| Windows | 不在 Mac 范围内 | 本次未执行 Windows 验收 |
| 导片助手打包 | **PASS** | 最终 r2 app 与 ZIP 已生成，ad-hoc 签名，`codesign --verify --deep --strict -v` 退出 0，`spctl` rejected 为此签名方式的预期结果 |
| 公证 | **不适用 / 用户决定跳过** | 自用 Mac，用户已决定采用 ad-hoc 签名 |

### 2026-11-12 导片助手实测结果

本机证据归档为 `Cetacea-Release-20261112/evidence/RESULTS-20261112.md`。最终候选为
`Photo_Importer_导片助手-2.6.1-AIAPI-20261112-r2.app`，以下计数来自该轮实际运行。

| 检查 | 结果 | 计数与范围 |
| --- | --- | --- |
| 后端完整 pytest | PASS | 298 passed、0 failed、11 skipped，另 118 subtests PASS，源码固定路径缺 Core Image helper 5 项、指定真实 RAW fixture 缺失 6 项 |
| 顶层 Python | PASS | 36 passed、0 failed、0 skipped，另 25 subtests PASS |
| 顶层 JavaScript | PASS | 20 passed、0 failed、0 skipped，shell 内部另含 14 项检查 |
| phase2 混合引擎 | PASS | 1 个 Python 方法，覆盖两个混合续导方向 |
| phase2 bridge | PASS | 24 项检查，源码与最终包内后台均通过 |
| phase2 transport | PASS | 53 项检查 |
| phase2 worker lifecycle | PASS | 8 项检查 |
| 包内引擎冒烟 | PASS | 18 项检查，覆盖真实 ASAR、Worker、Python 后台与原生 IO |
| README legacy 冻结 golden 对照 | **FAIL** | 缺原始冻结基准 `golden-provenance.json` 和 `legacy-golden.json` |
| README Ingesto 冻结 golden 对照 | **FAIL** | 同一原始冻结基准缺口 |
| 真实照片本地全量导入 | PASS | planned 10、copied 10、verified 10、skipped 0、errors 0，5 NEF + 5 JPG |
| 同源同项目重复执行 | PASS | planned 10、copied 0、verified-existing 10、skipped 10、errors 0，既有目标文件元数据保持一致 |
| 文件名范围计划 | PASS | `DSC_2650` 至 `DSC_2657`，3 对 NEF/JPG，共 6 个物理文件，仅生成计划 |
| SMB 全量计划、批准、执行 | PASS | planned 10、copied 10、verified 10、skipped 0、errors 0，37.825 秒，3.768 MiB/s |
| SMB 同源重复执行 | PASS | planned 10、copied 0、verified-existing 10、skipped 10、errors 0，诊断补测亦通过 |
| SMB 执行中途取消 | PASS | planned 50、copied 1、verified 1、skipped 0、errors 0，cancelled=true，正式位置为 1 个已校验文件 |
| SMB 取消后续导 | PASS（API 与 manifest） | planned 50、copied 49、verified-existing 1、skipped 1、errors 0，最终 50 文件 verified，manifest complete、catalog_complete=true，无重复与正式位置半截文件 |
| SMB 附加时间戳保持检查 | **FAIL / 待查** | 续导后先前已完成的 1 个 JPEG 的 mtime、ctime 改变，size、device、inode、mode 保持一致，根因未定 |

SMB 计数采用产品 API 与 schema 2 manifest，目标限定于 `CETACEA-SMB-Test-20261112`。
首轮重复执行的附加元数据相等断言失败，缺少比较前快照，具体差异无法还原。
诊断补测保存扫描前后与执行后快照，全部字段差值为空。续导的附加时间戳检查再次失败，
已有 before/after 证据，作为待查局限保留。中途取消和最终续导检查均未发现 `.cetacea-copy` 残留。
本机补测证据归档为 `Cetacea-Release-20261112/evidence/smb-20261112/SMB-RESULTS-20261112.md`。

本轮生成的 legacy/Ingesto 合同对照为 23 个向量一致，参照为本轮 legacy 执行器，原始冻结 golden 的两项 FAIL 继续保留。
首包漏打包 macOS RAW 与 USB 原生组件已在最终 r2 包中修复，两个 arm64 helper
均存在且各自的 `codesign` 校验通过，修复与构建回归已提交至 importer PR #3，状态为未合并。
[导片助手修复 PR #3](https://github.com/wj3529805-netizen/cetacea-photo-importer/pull/3)。

本次在 Mac 的 Python 3.14.8（用户指定 `.venv-20261112`）复跑全量自动化，
最终为 **396 passed、4 skipped，60.00 秒**，退出码 0。
前次开发全量为 396 passed、4 skipped，55.02 秒，相较基线新增 19 项测试，定向回归为 78 passed。
本次首轮为 395 passed、1 failed、4 skipped，R4 合成拔卡测试未捕获移除时的部分文件，
返回 `FAIL_UNVERIFIED_INTERRUPTION`。该项单独复跑 1 passed 后，全量复跑通过，原失败证据保留。
本机复跑日志为 `smb-20261112/harness-pytest*.{stdout.log,stderr.log,result.json}`，
失败历史见 [已知风险](KNOWN_RISKS.md#2026-11-12-验收文档补结果复跑)。
全量命令为：

```sh
env -u DEEPSEEK_API_KEY -u CETACEA_REALMODEL -u CETACEA_HARNESS_DIR \
  .venv-20261112/bin/python -m pytest -q
```

4 个跳过项为收集阶段的模块级跳过，与基线相同：真实模型相关模块未启用，
以及缺少 Harness 依赖的相关模块；未调用真实模型。
已有 LR 批量登记的真实历史不替代真实崩溃恢复验收，
SMB/NAS 与导片助手结果采用上表对应实测记录，Windows 仍未执行。

## NOT_COVERED / 局限（原 2026-11-03 范围；新日常结果见上节）

- R3 吞吐量只有 55 张冷读的约 **97 MB/s** 可作为速度数据。45 张的 788 MB/s 和 9 张的 758 MB/s 按缓存已热的重复读取假设处理，**不能作为速度证据**；并未验证缓存状态。
- R3 仅运行 ingest；R3 和 R4 均未运行 Lightroom，无论 MOCK 还是真实版本。R2 文件系统检查中的 Lightroom 是明确标记的 MOCK，真实 Lightroom 冒烟独立执行。
- R4 的 3 MB/s 限速和文件中途暂停由测试人为施加，速度不能说明产品速度。通过说明故意暂停复制时拔卡的行为，并不证明任意自然拔卡都通过。前两次 INTERRUPTION_NOT_ACHIEVED / FAIL_STOPPED 均保留为历史。
- 仅一张卡、一个读卡器、一台 Mac 和一个测试文件夹。早期 55 张及 45 张的 HE/HE★ 分类来自头部 tag `0x0051`，其 subtype report 没有 `raw_strip_bits_per_pixel`；后续 9 张报告有 strip bpp 佐证。Z6III HE 无星样片的 tag 为 13、3.0 bpp。LOSSLESS 帧的 tag 为 3，但 bpp 规则仅对恒定码率 HE/HE★ 作佐证，不能佐证 LOSSLESS；[类型报告](../evidence/mac-r3/run-20261103-214716/subtype-report.json)记录其未获 bpp 佐证。
- 未覆盖 Windows、SMB/NAS、断电、catalog 写入时崩溃、大型长期批次、其他读卡器或卡、Photoshop、真实客户数据和生产 Lightroom catalog。
- Linux 全量测试在本文件编写前的 HEAD `3673cff` 为 **173 passed、4 skipped**；Linux 测试结果不等于 macOS 结果。

## R5 隐私与证据

[脱敏映射](../evidence/mac-r5/desensitization-map.json)记录 122 个文件：个人主目录路径替换为 `<HOME>`，三枚真实卷 UUID 及其前缀替换为 `<VOLUME_UUID:...>` 等占位符；分别命中主目录 1006 次、完整 UUID 40 次、8 位前缀 3 次。证据 README 附有事后脱敏说明；[隐私守卫测试](../tests/test_privacy_guard.py)检查约定的残留。

保留 harness 会话/请求 UUID 和 APFS 类型 GUID 以维持运行标识与类型信息；卷名、`<HOME>/Documents/ChatGPT/...` 下的项目文件夹名及公开仓库 URL 中 GitHub 用户名也保留。历史读回中旧公开样片的 SHA-256、第三方版权文字和第三方相机序列号保留以记录实际运行；新样片内嵌机身及镜头序列号经所有者同意公开，快门计数随原文件保留。详见 [R5 说明](../evidence/mac-r5/README.md) 和 [样片说明](../samples/README.md)。

仓库公开，Git 历史仍含原始标识；脱敏仅影响当前树及未来克隆后的工作文件，不影响历史。修改后的计划不能重新验证原 `plan_digest`，映射保留修改前后哈希以便审计。

## 已决定（2026-11-03 22:08；2026-11-06 补充代码许可）

1. 所有者选择公开仓库，不重写 Git 历史。
2. 新样片许可：All rights reserved by the owner (晶 / repo owner); permission granted only for testing within this project (my-harness-project); no other use or redistribution. 中文译文见 [samples/LICENSE.txt](../samples/LICENSE.txt)；所有者同意公开内嵌机身和镜头序列号。
3. 历史证据中旧样片的署名、SHA-256 和第三方相机序列号有意保留。
4. 保留 harness UUID、卷名和项目文件夹名。
5. 仓库源代码许可已选择 MIT，已添加根目录 [LICENSE](../LICENSE)；样片仍适用独立的 `samples/LICENSE.txt`。

## 待用户决定

1. 合并到 phase1：见提交记录。
