# R1–R5 最终验收摘要

截至 2026-11-03，以下结论只适用于实际执行的范围；保留失败和未覆盖项。背景与操作细节见 [macOS 验证记录](MACOS_VALIDATION.md) 和 [R3/R4 操作说明](MAC_R3_R4_RUNBOOK.md)。

| 项目 | 实际执行范围 | 结果 | 证据 | 局限 |
| --- | --- | --- | --- | --- |
| R1 | 授权重跑真实 AI 会话：DeepSeek、受限 Harness、真实 Lightroom，单张公开样片及测试 catalog | PASS_IN_SCOPE；首次运行 FAIL，保留历史 | [重跑](../evidence/mac-r1/retry-1/result.json)、[首次](../evidence/mac-r1/result.json) | 有限样本；首次传输失败根因未确定 |
| R2 | exFAT SD 目标；文件系统检查使用 MOCK Lightroom，另做真实 Lightroom 冒烟 | 原运行因 AppleDouble 被误判 orphan 而 FAIL_STOPPED；修复 `fdfce5a` 后 rerun2 单样本 PASS_IN_SCOPE | [原结果](../evidence/mac-r2/result.json)、[重跑结果](../evidence/mac-r2-rerun2/result.json)、[验证记录](MACOS_VALIDATION.md) | MOCK 故障与重试检查和独立真实 Lightroom 冒烟各自有效，不能互相替代；首次重跑的验收脚本解析失败亦保留 |
| R3 193556 | 测试文件夹，45 张 HE★，仅 ingest | PARTIAL_NOT_COVERED | [结果](../evidence/mac-r3/run-20261103-193556/result.json)、[类型](../evidence/mac-r3/run-20261103-193556/subtype-report.json)、[计时](../evidence/mac-r3/run-20261103-193556/timing.json) | 未覆盖 HE；速度不可用 |
| R3 202435 | 测试文件夹，55 张 HE★，仅 ingest，冷读约 97 MB/s | PARTIAL_NOT_COVERED | [结果](../evidence/mac-r3/run-20261103-202435/result.json)、[类型](../evidence/mac-r3/run-20261103-202435/subtype-report.json)、[计时](../evidence/mac-r3/run-20261103-202435/timing.json) | 未覆盖 HE；单次冷读 |
| R3 214716 | 测试文件夹，7 张 HE★、1 张 HE、1 张 LOSSLESS，仅 ingest | PASS | [结果](../evidence/mac-r3/run-20261103-214716/result.json)、[类型](../evidence/mac-r3/run-20261103-214716/subtype-report.json)、[读回](../evidence/mac-r3/run-20261103-214716/readback.json)、[计时](../evidence/mac-r3/run-20261103-214716/timing.json) | 单次、单文件夹；速度不可用 |
| R4 202626 | 拔卡尝试 | INTERRUPTION_NOT_ACHIEVED | [结果](../evidence/mac-r4/run-20261103-202626/result.json) | 观察到进度前复制已完成 |
| R4 203649 | 限速拔卡尝试 | FAIL_STOPPED | [结果](../evidence/mac-r4/run-20261103-203649/result.json) | 观察到拔卡前子进程退出 |
| R4 205826 | 人为限速、文件中途暂停后拔卡及恢复 | PASS | [结果](../evidence/mac-r4/run-20261103-205826/result.json) | 拔卡时 part 大小记录为 0；后续使用更严格判据 |
| R4 215049 | 仅拔卡前清点 | 未完成，无结果 | [清点](../evidence/mac-r4/run-20261103-215049/pre-inventory.json) | 不计作运行通过 |
| R4 215121 | 人为限速、文件中途暂停后拔卡及恢复 | PASS，更严格判据：拔卡时 held part 存在，首个失败为该文件的 EIO | [结果](../evidence/mac-r4/run-20261103-215121/result.json)、[说明](../evidence/mac-r4/run-20261103-215121/README.md) | 受控暂停场景，见下文 |
| R5 | 替换样片、对当前树事后脱敏 | 已在 `prep/R5` 执行 | [说明](../evidence/mac-r5/README.md)、[映射](../evidence/mac-r5/desensitization-map.json)、[样片](../samples/README.md) | 仓库公开；Git 历史未重写 |

R3 214716 的 HE 帧是 DSC_9725.NEF；其[清点](../evidence/mac-r3/run-20261103-214716/inventory-before.json)与目的地读回 SHA-256 均为 `d77f05b50d569de25ce56c435bf7c8d3b40abc250d0a3acee4c376645e941f7e`，与 [samples/Nikon-Z6III-HE-DSC_9725.NEF](../samples/README.md) 所记哈希一致。

## NOT_COVERED / 局限

- R3 吞吐量只有 55 张冷读的约 **97 MB/s** 可作为速度数据。45 张的 788 MB/s 和 9 张的 758 MB/s 按缓存已热的重复读取假设处理，**不能作为速度证据**；并未验证缓存状态。
- R3 仅运行 ingest；R3 和 R4 均未运行 Lightroom，无论 MOCK 还是真实版本。R2 文件系统检查中的 Lightroom 是明确标记的 MOCK，真实 Lightroom 冒烟独立执行。
- R4 的 3 MB/s 限速和文件中途暂停由测试人为施加，速度不能说明产品速度。通过说明故意暂停复制时拔卡的行为，并不证明任意自然拔卡都通过。前两次 INTERRUPTION_NOT_ACHIEVED / FAIL_STOPPED 均保留为历史。
- 仅一张卡、一个读卡器、一台 Mac 和一个测试文件夹。早期 55 张及 45 张的 HE/HE★ 分类来自头部 tag `0x0051`，其 subtype report 没有 `raw_strip_bits_per_pixel`；后续 9 张报告有 strip bpp 佐证。Z6III HE 无星样片的 tag 为 13、3.0 bpp。LOSSLESS 帧的 tag 为 3，但 bpp 规则仅对恒定码率 HE/HE★ 作佐证，不能佐证 LOSSLESS；[类型报告](../evidence/mac-r3/run-20261103-214716/subtype-report.json)记录其未获 bpp 佐证。
- 未覆盖 Windows、SMB/NAS、断电、catalog 写入时崩溃、大型长期批次、其他读卡器或卡、Photoshop、真实客户数据和生产 Lightroom catalog。
- Linux 全量测试在本文件编写前的 HEAD `3673cff` 为 **173 passed、4 skipped**；Linux 测试结果不等于 macOS 结果。

## R5 隐私与证据

[脱敏映射](../evidence/mac-r5/desensitization-map.json)记录 122 个文件：个人主目录路径替换为 `<HOME>`，三枚真实卷 UUID 及其前缀替换为 `<VOLUME_UUID:...>` 等占位符；分别命中主目录 1006 次、完整 UUID 40 次、8 位前缀 3 次。证据 README 附有事后脱敏说明；[隐私守卫测试](../tests/test_privacy_guard.py)检查约定的残留。

保留 harness 会话/请求 UUID 和 APFS 类型 GUID 以维持运行标识与类型信息；卷名、`<HOME>/Documents/ChatGPT/...` 下的项目文件夹名及公开仓库 URL 中 GitHub 用户名也保留。历史读回中旧公开样片的 SHA-256、第三方版权文字和第三方相机序列号保留以记录实际运行；新样片内嵌机身及镜头序列号和快门计数按所有者同意发布的原文件保留。详见 [R5 说明](../evidence/mac-r5/README.md) 和 [样片说明](../samples/README.md)。

仓库公开，Git 历史仍含原始标识；脱敏仅影响当前树及未来克隆后的工作文件，不影响历史。修改后的计划不能重新验证原 `plan_digest`，映射保留修改前后哈希以便审计。

## 待用户决定

1. 是否重写 Git 历史；目前未做。
2. 新样片的 CC0 许可证措辞是否获所有者确认。
3. 是否进一步脱敏历史旧样片的 SHA、署名及序列号。
4. 是否接受保留 harness UUID、卷名和项目文件夹名。
5. 是否将 `prep/R5` 合并到 `phase1`。
