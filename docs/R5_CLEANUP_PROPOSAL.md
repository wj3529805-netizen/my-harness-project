# R5 清理提案（待用户决定）

本文件只是提案；未实施脱敏、许可证处置、提交或客户数据放行。范围为 phase1 `63a691c` 的已跟踪当前树；清单来自审核者 `/workspace/r5tmp/r5_inventory.md`，该基线共有 384 个 tracked 文件。并发的 R3/R4 文件不在本清单内，执行前须重新清点。禁止改写 Git 历史；若获批准，只在当前树脱敏并以**新提交**记录。保留证据原始哈希、真实与 MOCK 标记、失败及验收结论；脱敏副本不能冒充原始记录。源卡只读、目标不覆盖和目标重新读取 SHA-256 等既有边界不变。

## 标识清单

`<HOME>` 在 **101 个文件、997 次出现**；独立复核 `rg -c` 为 **101 个文件、673 个匹配行**。一行可含多次出现，口径不同，并无矛盾。主要路径族包括项目目录、film-sim 目录和 `~/.config/lightroom-mcp/token` 路径。已检查 tracked 文件中 token 相关文本：所见是 token 文件路径或说明，未见 token 值；这不是对所有可能秘密的保证。JSON 中还有 `\u5de5` 和 `\\u5de5` 等不同嵌套转义层，简单替换原始中文路径会遗漏。用户名 `mac` 在本次标识清单中以路径形式出现；对 hostname、host_name、computername、localhostname、`.local` 的 tracked 文本搜索无结果，未发现主机名（不等于证明任意未知主机名不存在）。

按目录的小计（文件数；每个文件只计入一个目录）：

- `docs/`：2
- `evidence/mac-acceptance/`：33
- `evidence/mac-acceptance-merged/`：40
- `evidence/mac-r1/`：16
- `evidence/mac-r2/`：4
- `evidence/mac-r2-rerun/`：3
- `evidence/mac-r2-rerun2/`：3


<details><summary><HOME> 全部文件及出现次数（997 次）</summary>

- `evidence/mac-acceptance-merged/interruption-real-calls.jsonl`：150
- `evidence/mac-r2-rerun2/real-filesystem-events.jsonl`：117
- `evidence/mac-r2-rerun/real-filesystem-events.jsonl`：80
- `evidence/mac-r2/real-filesystem-events.jsonl`：68
- `evidence/mac-acceptance-merged/single-real-calls.jsonl`：51
- `evidence/mac-acceptance-merged/harness-install.txt`：49
- `evidence/mac-r1/retry-1/errors.txt`：42
- `evidence/mac-acceptance/real-cc0-calls.jsonl`：34
- `evidence/mac-acceptance-merged/retry-resume-console.txt`：23
- `evidence/mac-acceptance/devices-20261102-220045/physical-lightroom-log.txt`：22
- `evidence/mac-r1/retry-1/real-session.jsonl`：18
- `evidence/mac-acceptance-merged/interruption-mcp.jsonl`：16
- `evidence/mac-acceptance-merged/single-mcp.jsonl`：16
- `evidence/mac-acceptance-merged/single-console.txt`：11
- `evidence/mac-acceptance/cc0-full-log.txt`：11
- `evidence/mac-acceptance/interruption-retry-log.txt`：9
- `evidence/mac-acceptance-merged/retry-resume-database.json`：8
- `evidence/mac-acceptance-merged/retry-resume-mcp.jsonl`：8
- `evidence/mac-acceptance-merged/tamper-export-mcp.jsonl`：8
- `evidence/mac-acceptance-merged/tamper-preset-mcp.jsonl`：8
- `evidence/mac-r2-rerun/real-enotsup-checks.json`：8
- `evidence/mac-r2-rerun2/real-enotsup-checks.json`：8
- `evidence/mac-r2/failure-analysis.json`：8
- `evidence/mac-acceptance-merged/interruption-approval.json`：6
- `evidence/mac-acceptance-merged/interruption-console.txt`：6
- `evidence/mac-acceptance-merged/single-approval.json`：6
- `evidence/mac-acceptance-merged/tamper-export-approval.json`：6
- `evidence/mac-acceptance-merged/tamper-export-real-calls.jsonl`：6
- `evidence/mac-acceptance-merged/tamper-preset-approval.json`：6
- `evidence/mac-acceptance-merged/tamper-preset-real-calls.jsonl`：6
- `evidence/mac-acceptance/A10-repeat-mcp-result.json`：6
- `evidence/mac-acceptance/interruption-start-log.txt`：6
- `evidence/mac-r1/retry-1/human-cli-approval.json`：6
- `evidence/mac-r1/real-session.jsonl`：5
- `evidence/mac-r2-rerun/result.json`：5
- `evidence/mac-acceptance-merged/final-inventory.json`：4
- `evidence/mac-acceptance-merged/interruption-plan.json`：4
- `evidence/mac-acceptance-merged/interruption-result.json`：4
- `evidence/mac-acceptance-merged/retry-resume-result.json`：4
- `evidence/mac-acceptance-merged/single-database.json`：4
- `evidence/mac-acceptance-merged/single-plan.json`：4
- `evidence/mac-acceptance-merged/single-result.json`：4
- `evidence/mac-acceptance-merged/tamper-export-plan.json`：4
- `evidence/mac-acceptance-merged/tamper-preset-plan.json`：4
- `evidence/mac-acceptance/cc0-initial-log.txt`：4
- `evidence/mac-acceptance/final-test-catalog-metadata.json`：4
- `evidence/mac-acceptance/real-first-log.txt`：4
- `evidence/mac-acceptance/real-mcp-status-log.txt`：4
- `evidence/mac-r1/retry-1/final-database.json`：4
- `evidence/mac-r1/retry-1/final-task.json`：4
- `evidence/mac-r1/retry-1/plan.json`：4
- `evidence/mac-acceptance-merged/interruption-database.json`：3
- `evidence/mac-acceptance-merged/retry-resume-develop-readback.json`：3
- `evidence/mac-acceptance/interruption-checks.json`：3
- `evidence/mac-acceptance/real-calls.jsonl`：3
- `evidence/mac-acceptance/real-mcp-status-final-log.txt`：3
- `evidence/mac-acceptance/real-preview-log.txt`：3
- `evidence/mac-r2/acceptance-console.txt`：3
- `evidence/mac-r2/result.json`：3
- `docs/MACOS_VALIDATION.md`：2
- `evidence/mac-acceptance-merged/collection.txt`：2
- `evidence/mac-acceptance-merged/environment.json`：2
- `evidence/mac-acceptance-merged/interruption-catalog-guard.json`：2
- `evidence/mac-acceptance-merged/retry-resume-catalog-guard.json`：2
- `evidence/mac-acceptance-merged/single-catalog-guard.json`：2
- `evidence/mac-acceptance-merged/tamper-export-catalog-guard.json`：2
- `evidence/mac-acceptance-merged/tamper-export-database.json`：2
- `evidence/mac-acceptance-merged/tamper-preset-catalog-guard.json`：2
- `evidence/mac-acceptance-merged/tamper-preset-database.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-pipeline-20261102T141051Z-76e5e0c7.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-probe-20261102T141045Z-879e1713.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-retry-20261102T141052Z-8ff4e7b0.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/physical-to-local-apfs.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/setup.json`：2
- `evidence/mac-acceptance/interruption-ready.json`：2
- `evidence/mac-acceptance/mcp-boundary-clone.json`：2
- `evidence/mac-acceptance/mcp-boundary.json`：2
- `evidence/mac-r1/catalog-guard.json`：2
- `evidence/mac-r1/retry-1/catalog-guard-before-execute.json`：2
- `evidence/mac-r1/retry-1/model-turn-summaries.json`：2
- `evidence/mac-r1/retry-1/preapproval-database.json`：2
- `evidence/mac-r2-rerun2/real-catalog-guard.json`：2
- `docs/ROADMAP.md`：1
- `evidence/mac-acceptance-merged/pytest-final-exit.json`：1
- `evidence/mac-acceptance-merged/single-develop-readback.json`：1
- `evidence/mac-acceptance/A10-repeat-mcp-log.txt`：1
- `evidence/mac-acceptance/cc0-assets.json`：1
- `evidence/mac-acceptance/cc0-full-checks.json`：1
- `evidence/mac-acceptance/cc0-full-report.json`：1
- `evidence/mac-acceptance/check-env-final.txt`：1
- `evidence/mac-acceptance/develop-after.json`：1
- `evidence/mac-acceptance/develop-before.json`：1
- `evidence/mac-acceptance/enotsup-regression.json`：1
- `evidence/mac-acceptance/environment.json`：1
- `evidence/mac-acceptance/interruption-assets-after-close.json`：1
- `evidence/mac-r1/check-env.txt`：1
- `evidence/mac-r1/preflight.json`：1
- `evidence/mac-r1/retry-1/catalog-guard-final.json`：1
- `evidence/mac-r1/retry-1/develop-readback.json`：1
- `evidence/mac-r1/retry-1/retry-authorization-and-guard.json`：1

</details>


三个真实卷 UUID 在下表仅显示前 8 位及**大写完整 UUID 的 UTF-8 SHA-256 前 16 位**；哈希前缀有可关联性，不是秘密或匿名保证。


<details><summary><VOLUME_UUID:39f4499d9fb1c7a3>… / SHA-256 前缀 39f4499d9fb1c7a3：exFAT SD card (R2 target): 15 files, 15 occurrences</summary>

- `docs/MACOS_DEVICE_VALIDATION.md`：1
- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：1
- `evidence/mac-acceptance/devices-20261102-220045/physical-to-local-apfs.json`：1
- `evidence/mac-acceptance/devices-20261102-220045/setup.json`：1
- `evidence/mac-r2-rerun/card-write-authorization.json`：1
- `evidence/mac-r2-rerun/run_r2_rerun.py`：1
- `evidence/mac-r2-rerun2/card-write-authorization.json`：1
- `evidence/mac-r2-rerun2/run_r2_rerun2.py`：1
- `evidence/mac-r2/card-write-authorization.json`：1
- `evidence/mac-r2/disk7s1-diskutil-info-text.json`：1
- `evidence/mac-r2/disk7s1-diskutil-info.plist`：1
- `evidence/mac-r2/mounted-card-candidates.json`：1
- `evidence/mac-r2/run_r2.py`：1
- `evidence/mac-r2/sd-existing-content-inventory.json`：1
- `evidence/mac-r2/write-proposal.json`：1

</details>


<details><summary><VOLUME_UUID:5ae0b1a37395edf7>… / SHA-256 前缀 5ae0b1a37395edf7：Nikon card volume (disk6s1): 7 files, 7 occurrences</summary>

- `docs/MACOS_DEVICE_VALIDATION.md`：1
- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：1
- `evidence/mac-acceptance/devices-20261102-220045/physical-to-local-apfs.json`：1
- `evidence/mac-acceptance/devices-20261102-220045/setup.json`：1
- `evidence/mac-r2/disk6s1-diskutil-info-text.json`：1
- `evidence/mac-r2/disk6s1-diskutil-info.plist`：1
- `evidence/mac-r2/mounted-card-candidates.json`：1

</details>


<details><summary><VOLUME_UUID:0d700d67e691ff25>… / SHA-256 前缀 0d700d67e691ff25：APFS volume (Cetacea Studio?): 6 files, 18 occurrences</summary>

- `docs/MACOS_DEVICE_VALIDATION.md`：1
- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：4
- `evidence/mac-acceptance/devices-20261102-220045/apfs-pipeline-20261102T141051Z-76e5e0c7.json`：4
- `evidence/mac-acceptance/devices-20261102-220045/apfs-probe-20261102T141045Z-879e1713.json`：4
- `evidence/mac-acceptance/devices-20261102-220045/apfs-retry-20261102T141052Z-8ff4e7b0.json`：4
- `evidence/mac-acceptance/devices-20261102-220045/setup.json`：1

</details>


APFS 通用 container type GUID 为类型标识而非设备唯一标识，可保留；4 文件、8 次：

- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-pipeline-20261102T141051Z-76e5e0c7.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-probe-20261102T141045Z-879e1713.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/apfs-retry-20261102T141052Z-8ff4e7b0.json`：2


另有 33 个不同的 UUID 形态字符串、141 次出现，清单将其归为 Harness session、request、Lightroom catalog ID，而非卷标识。建议保留以维持事件关联和证据可读性；它们仍可跨记录关联，公开前须由用户接受其风险。


<details><summary>/Volumes/Cetacea Studio：9 files, 195 occurrences</summary>

- `evidence/mac-acceptance/devices-20261102-220045/apfs-retry-20261102T141052Z-8ff4e7b0.json`：61
- `evidence/mac-acceptance/devices-20261102-220045/apfs-pipeline-20261102T141051Z-76e5e0c7.json`：52
- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：47
- `evidence/mac-acceptance/devices-20261102-220045/physical-lightroom-calls.jsonl`：22
- `evidence/mac-acceptance/devices-20261102-220045/apfs-probe-20261102T141045Z-879e1713.json`：7
- `docs/MACOS_DEVICE_VALIDATION.md`：2
- `evidence/mac-acceptance/devices-20261102-220045/setup.json`：2
- `evidence/mac-acceptance/devices-20261102-220045/image-create-hdiutil.json`：1
- `evidence/mac-acceptance/devices-20261102-220045/image-create.json`：1

</details>


<details><summary>/Volumes/NIKON Z6_3：55 files, 540 occurrences</summary>

- `evidence/mac-r2-rerun2/real-filesystem-events.jsonl`：140
- `evidence/mac-r2-rerun/real-filesystem-events.jsonl`：97
- `evidence/mac-r2/real-filesystem-events.jsonl`：83
- `evidence/mac-r2/failure-analysis.json`：23
- `evidence/mac-r2-rerun2/appledouble-skipped.json`：21
- `evidence/mac-r2-rerun/real-enotsup-checks.json`：16
- `evidence/mac-r2-rerun2/real-enotsup-checks.json`：16
- `evidence/mac-r2/result.json`：8
- `evidence/mac-r2/failure-database.json`：7
- `evidence/mac-acceptance/devices-20261102-220045/setup.json`：6
- `evidence/mac-r2-rerun2/mock-manifests-readback.json`：6
- `evidence/mac-r2/failure-manifests.json`：6
- `evidence/mac-acceptance/devices-20261102-220045/apfs-ingest-20261102T141050Z-e8d2c9e0.json`：4
- `evidence/mac-acceptance/devices-20261102-220045/physical-to-local-apfs.json`：4
- `evidence/mac-r2-rerun/controlled-partial-export.json`：4
- `evidence/mac-r2-rerun/mock-approval.json`：4
- `evidence/mac-r2-rerun/mock-plan.json`：4
- `evidence/mac-r2-rerun/mock-retry-result.json`：4
- `evidence/mac-r2-rerun2/controlled-partial-export.json`：4
- `evidence/mac-r2-rerun2/mock-approval.json`：4
- `evidence/mac-r2-rerun2/mock-plan.json`：4
- `evidence/mac-r2-rerun2/mock-retry-result.json`：4
- `evidence/mac-r2-rerun2/real-approval.json`：4
- `evidence/mac-r2-rerun2/real-plan.json`：4
- `evidence/mac-r2-rerun2/real-result.json`：4
- `evidence/mac-r2/acceptance-console.txt`：4
- `evidence/mac-r2/controlled-partial-export.json`：4
- `evidence/mac-r2/mock-approval.json`：4
- `evidence/mac-r2/mock-plan.json`：4
- `evidence/mac-r2/mock-retry-result.json`：4
- `evidence/mac-r2-rerun/mock-previews.json`：3
- `evidence/mac-r2-rerun2/mock-previews.json`：3
- `evidence/mac-acceptance/devices-20261102-220045/physical-source-before.json`：2
- `evidence/mac-r2-rerun/card-write-authorization.json`：2
- `evidence/mac-r2-rerun/mock-tasks.json`：2
- `evidence/mac-r2-rerun2/card-write-authorization.json`：2
- `evidence/mac-r2-rerun2/mock-tasks.json`：2
- `evidence/mac-r2-rerun2/real-tasks.json`：2
- `evidence/mac-r2/card-write-authorization.json`：2
- `evidence/mac-r2/mounted-card-candidates.json`：2
- `evidence/mac-r2/sd-existing-content-summary.json`：2
- `evidence/mac-r2/write-proposal.json`：2
- `docs/MACOS_VALIDATION.md`：1
- `evidence/mac-r2-rerun/preview-before-retry.json`：1
- `evidence/mac-r2-rerun2/preview-before-retry.json`：1
- `evidence/mac-r2-rerun2/real-assets.json`：1
- `evidence/mac-r2-rerun2/real-develop-readback.json`：1
- `evidence/mac-r2-rerun2/real-previews.json`：1
- `evidence/mac-r2/disk6s1-diskutil-info-text.json`：1
- `evidence/mac-r2/disk6s1-diskutil-info.plist`：1
- `evidence/mac-r2/disk7s1-diskutil-info-text.json`：1
- `evidence/mac-r2/disk7s1-diskutil-info.plist`：1
- `evidence/mac-r2/preview-before-retry.json`：1
- `evidence/mac-r2/run_r2.py`：1
- `evidence/mac-r2/sd-existing-content-list.txt`：1

</details>


<details><summary>Ludger Heide：11 files, 80 occurrences</summary>

- `evidence/mac-acceptance/real-cc0-calls.jsonl`：30
- `evidence/mac-acceptance/final-test-catalog-metadata.json`：12
- `evidence/mac-acceptance-merged/interruption-real-calls.jsonl`：9
- `evidence/mac-acceptance-merged/retry-resume-develop-readback.json`：9
- `evidence/mac-acceptance-merged/single-develop-readback.json`：3
- `evidence/mac-acceptance-merged/single-real-calls.jsonl`：3
- `evidence/mac-acceptance/develop-after.json`：3
- `evidence/mac-acceptance/develop-before.json`：3
- `evidence/mac-r1/retry-1/develop-readback.json`：3
- `evidence/mac-r2-rerun2/real-develop-readback.json`：3
- `docs/MACOS_VALIDATION.md`：2

</details>


`Ludger Heide` 是 NEF 内嵌版权持有人，属于许可署名，不能当普通个人路径静默删掉；下述许可决定应保留来源与署名。

## 当前树脱敏设计（尚未编写或执行）

拟新增可审阅的 `scripts/r5_desensitize.py`：默认 dry-run，输出按文件、规则、命中次数及预期差异；只有显式 `--apply` 才写当前树。固定输入为审核后的 tracked 文件清单，排除本提案中解释规则的示例和映射文件；拒绝符号链接、非文本、未知编码及未预期的变化，失败停止。只处理文本/JSON；二进制跳过并报告。`evidence/mac-r2/*.plist` 已核对为 XML 文本 plist，应按文本处理并验证 plist 可解析，不能按扩展名当作二进制跳过。

按最长、最具体规则先匹配，计数不重复；下列示例中的原文仅供审阅：

| 输入 | 输出 |
|---|---|
| `<HOME>/Documents/ChatGPT/AI工作台/my-harness-project` | `<REPO>` |
| `<HOME>/.config/lightroom-mcp/token` 或 `~/.config/lightroom-mcp/token` | `<HOME>/.config/lightroom-mcp/token` |
| 其他 `<HOME>` | `<HOME>` |
| 每个已识别真实卷 UUID（大小写统一后计算） | `<VOLUME_UUID:sha256-prefix16>`，prefix 为其大写完整 UUID 的 SHA-256 前 16 位 |
| `/Volumes/NIKON Z6_3` | `<VOLUME:SD-CARD-1>` |
| `/Volumes/Cetacea Studio` | `<VOLUME:TEST-TARGET>` |

卷名以准确子串替换，保留后续空格等原字符；其他卷或路径须由人工审查，不臆测归类。JSON 解析后递归改字符串叶子，对已知嵌套 JSON 字符串递归识别并重写，覆盖 Unicode 及多层转义；再尽量保持原缩进、换行、键顺序及 escape 风格序列化。无法保持格式或安全辨识嵌套内容时停止并人工审核；不能假设通用 JSON re-dump 可以无损保持原格式。`.txt`、`.md`、`.py`、`.jsonl` 用受控文本替换；JSONL 逐行验证 JSON，并处理嵌套转义。每类均验证语义变化只限明确规则。`evidence/mac-r2*/run_r2*.py` 内的路径/UUID 守卫需单独审查，改为 CLI/env 显式提供并保留身份检查；修改后的脚本不再是原运行的精确复现，原脚本由以下映射和 Git 历史保留，不得声称运行结果改变或重新验证。

**证据完整性：**修改任何证据文件都会改变它自身的 SHA-256；其他证据可能嵌入其哈希。逐一识别引用并标注原/脱敏文件关系，保留原值，不能静默把原摘要改成新摘要或伪称新文件就是当时的原件。`src/cetacea/core.py` 的 `digest(plan)` 对排序、紧凑 JSON 的整个 plan 求 SHA-256；扫描文件包含 `rel_path`、`dest_rel_path`，`destination` 是相对路径，源绝对路径用于扫描但不直接存进 plan。若包含 Lightroom 阶段，`lightroom.export.preview_root` 和 `library_root` 进入 plan，通常是绝对路径；现有证据中确有此类路径。替换这些路径会使原 `plan_digest` 不再匹配脱敏 plan，不能重新计算后冒充原批准。核查每个受影响计划，保留原摘要并明确标注脱敏文本不可用于原审批复验；如需复验，从历史取原始 blob 到受保护位置。

拟新增 `evidence/mac-r5/desensitization-map.json`，每个修改文件记录路径、修改前 blob 的 SHA-256、所属基线 commit 和 Git blob ID、新 SHA-256、规则命中及数量；另记录受影响的嵌入哈希和 plan_digest 关系与说明。映射不记录原始路径、完整卷 UUID 或 token 内容；先检查短哈希关联风险。历史原件仍可通过 Git 获取，**历史没有改写，标识仍在历史中**。若将来公开或向不应接触原标识的人分享仓库，仅脱敏当前树不够；需要另行授权后改写历史或建立不含旧历史的新仓库，并审查已有副本、缓存与派生物。

执行前比较清单基线与当前 HEAD，逐文件核对原 SHA、blob 与命中数；存在并发变化即停止重清点。dry-run 的规则命中总数与本清单原始字面出现次数交叉核对（重叠规则和转义解码另行列账，不强行相加），审阅差异及映射后才决定 `--apply`。应用后对被处理范围使用下列搜索验证目标原文和各转义形式无残留，单独排除本提案示例及必要的许可署名；解析所有受影响 JSON/JSONL/XML plist；验证映射前后 SHA、原始摘要引用关系、文件列表与计数；运行 `.venv/bin/python -m pytest`，如有失败原样记录到 `docs/KNOWN_RISKS.md`，不得削弱测试。运行不回显秘密的 secret scan 并人工审查日志；发现疑似秘密停止处理。测试通过不表示 macOS 或真实 Lightroom 已重新验证。若用户批准后另建提交，回滚用 revert 该提交；回滚会重新暴露当前树标识。

可选替代策略：接受在私有仓库保留标识。优点是原证据与脚本原样、摘要易复核，工作量小；缺点是任何获得仓库及历史权限者可关联路径、设备和会话，私有设置或成员变更也会扩大暴露。按要求执行 `gh repo view wj3529805-netizen/my-harness-project --json visibility -q .visibility` 返回连接 api.github.com 失败，因此**无法验证仓库当前是否私有**；不得据此假定为 private。当前任务禁止网络调用，不再重试；由用户在允许的环境自行确认。

## 样片许可冲突

记录表明公开样片 `Nikon-Z6.NEF` 为 25,994,889 bytes，SHA-256 `8ca94584578b35a422744c1a610174ce37df0691588edfdecaec3111b3fbbb02`，raw.pixls.us id 3581；发布方 README 标 CC0，文件内嵌 `(CC-BY-SA 4.0) Ludger Heide`，两者冲突尚未解决，`cc0` 目录名不是授权结论。来源与哈希依据 [MACOS_VALIDATION.md](MACOS_VALIDATION.md)，本次未联网核验发布方或摄影师。`git ls-files` 扩展名检查未发现 tracked NEF、JPG/JPEG 或 RAW；因此未发现提交的导出预览 JPG，但扩展名检查不能排除伪装扩展名的二进制。仓库提交了样片哈希、计划/清单、元数据及其内嵌版权读回等衍生记录。


<details><summary>精确样片 SHA-256 的全部 tracked 引用文件（由只读搜索生成）</summary>

- `docs/MACOS_VALIDATION.md`
- `evidence/mac-acceptance-merged/interruption-approval.json`
- `evidence/mac-acceptance-merged/interruption-before-retry-checks.json`
- `evidence/mac-acceptance-merged/interruption-database.json`
- `evidence/mac-acceptance-merged/interruption-mcp.jsonl`
- `evidence/mac-acceptance-merged/interruption-plan.json`
- `evidence/mac-acceptance-merged/interruption-result.json`
- `evidence/mac-acceptance-merged/interruption-source-before.json`
- `evidence/mac-acceptance-merged/retry-resume-database.json`
- `evidence/mac-acceptance-merged/retry-resume-mcp.jsonl`
- `evidence/mac-acceptance-merged/retry-resume-result.json`
- `evidence/mac-acceptance-merged/run_acceptance.py`
- `evidence/mac-acceptance-merged/single-approval.json`
- `evidence/mac-acceptance-merged/single-database.json`
- `evidence/mac-acceptance-merged/single-mcp.jsonl`
- `evidence/mac-acceptance-merged/single-plan.json`
- `evidence/mac-acceptance-merged/single-result.json`
- `evidence/mac-acceptance-merged/single-source-before.json`
- `evidence/mac-acceptance-merged/tamper-export-approval.json`
- `evidence/mac-acceptance-merged/tamper-export-database.json`
- `evidence/mac-acceptance-merged/tamper-export-mcp.jsonl`
- `evidence/mac-acceptance-merged/tamper-export-plan.json`
- `evidence/mac-acceptance-merged/tamper-export-source-before.json`
- `evidence/mac-acceptance-merged/tamper-preset-approval.json`
- `evidence/mac-acceptance-merged/tamper-preset-database.json`
- `evidence/mac-acceptance-merged/tamper-preset-mcp.jsonl`
- `evidence/mac-acceptance-merged/tamper-preset-plan.json`
- `evidence/mac-acceptance-merged/tamper-preset-source-before.json`
- `evidence/mac-acceptance/A10-repeat-mcp-result.json`
- `evidence/mac-acceptance/cc0-assets.json`
- `evidence/mac-acceptance/cc0-full-checks.json`
- `evidence/mac-acceptance/cc0-full-log.txt`
- `evidence/mac-acceptance/cc0-full-plan.json`
- `evidence/mac-acceptance/cc0-full-report.json`
- `evidence/mac-acceptance/cc0-full-result.json`
- `evidence/mac-acceptance/cc0-plan.json`
- `evidence/mac-acceptance/cc0-register-result.json`
- `evidence/mac-acceptance/interruption-assets-after-close.json`
- `evidence/mac-acceptance/interruption-checks.json`
- `evidence/mac-acceptance/interruption-failed-result.json`
- `evidence/mac-acceptance/interruption-library-before.json`
- `evidence/mac-acceptance/interruption-plan.json`
- `evidence/mac-acceptance/interruption-ready.json`
- `evidence/mac-acceptance/interruption-retry-result.json`
- `evidence/mac-acceptance/interruption-source-before.json`
- `evidence/mac-acceptance/sample-SHA256SUMS.txt`
- `evidence/mac-acceptance/source-before.json`
- `evidence/mac-r1/preflight.json`
- `evidence/mac-r1/retry-1/final-checks.json`
- `evidence/mac-r1/retry-1/final-database.json`
- `evidence/mac-r1/retry-1/final-task.json`
- `evidence/mac-r1/retry-1/human-cli-approval.json`
- `evidence/mac-r1/retry-1/model-turn-summaries.json`
- `evidence/mac-r1/retry-1/plan.json`
- `evidence/mac-r1/retry-1/preapproval-database.json`
- `evidence/mac-r1/retry-1/real-session.jsonl`
- `evidence/mac-r1/retry-1/source-after.json`
- `evidence/mac-r1/source-after.json`
- `evidence/mac-r1/source-before.json`
- `evidence/mac-r2-rerun/controlled-partial-export.json`
- `evidence/mac-r2-rerun/mock-approval.json`
- `evidence/mac-r2-rerun/mock-assets.json`
- `evidence/mac-r2-rerun/mock-plan.json`
- `evidence/mac-r2-rerun/mock-retry-result.json`
- `evidence/mac-r2-rerun/mock-task_steps.json`
- `evidence/mac-r2-rerun/mock-tasks.json`
- `evidence/mac-r2-rerun/real-source-before.json`
- `evidence/mac-r2-rerun/repeat-and-conflict.json`
- `evidence/mac-r2-rerun/run_r2_rerun.py`
- `evidence/mac-r2-rerun/source-before.json`
- `evidence/mac-r2-rerun2/controlled-partial-export.json`
- `evidence/mac-r2-rerun2/mock-approval.json`
- `evidence/mac-r2-rerun2/mock-assets.json`
- `evidence/mac-r2-rerun2/mock-manifests-readback.json`
- `evidence/mac-r2-rerun2/mock-plan.json`
- `evidence/mac-r2-rerun2/mock-retry-result.json`
- `evidence/mac-r2-rerun2/mock-task_steps.json`
- `evidence/mac-r2-rerun2/mock-tasks.json`
- `evidence/mac-r2-rerun2/real-approval.json`
- `evidence/mac-r2-rerun2/real-assets.json`
- `evidence/mac-r2-rerun2/real-plan.json`
- `evidence/mac-r2-rerun2/real-result.json`
- `evidence/mac-r2-rerun2/real-source-before.json`
- `evidence/mac-r2-rerun2/real-task_steps.json`
- `evidence/mac-r2-rerun2/real-tasks.json`
- `evidence/mac-r2-rerun2/repeat-and-conflict.json`
- `evidence/mac-r2-rerun2/result.json`
- `evidence/mac-r2-rerun2/run_r2_rerun2.py`
- `evidence/mac-r2-rerun2/source-before.json`
- `evidence/mac-r2/acceptance-console.txt`
- `evidence/mac-r2/controlled-partial-export.json`
- `evidence/mac-r2/failure-analysis.json`
- `evidence/mac-r2/failure-database.json`
- `evidence/mac-r2/failure-manifests.json`
- `evidence/mac-r2/mock-approval.json`
- `evidence/mac-r2/mock-plan.json`
- `evidence/mac-r2/mock-retry-result.json`
- `evidence/mac-r2/real-source-before.json`
- `evidence/mac-r2/result.json`
- `evidence/mac-r2/run_r2.py`
- `evidence/mac-r2/source-after.json`
- `evidence/mac-r2/source-before.json`
- `evidence/mac-r2/source-real-after.json`

</details>


| 选项 | 处理与影响 |
|---|---|
| (a) 保留样片作测试输入 | 在 `THIRD_PARTY.md` 和 README 加注，例如：`Nikon-Z6.NEF, Ludger Heide, raw.pixls.us #3581; embedded notice CC BY-SA 4.0; distributor states CC0; license discrepancy unresolved; source: https://raw.pixls.us/`。加上适用许可链接、变更说明及具体来源；署名不能自行解决授权冲突。若再分发或生成并分发预览等衍生作品，应评估 CC BY-SA 4.0 的署名及 ShareAlike 要求；当前预览 JPG 未跟踪，影响较低。再分发前建议向原摄影师核实授权。 |
| (b) 后续换为用户自拍测试 NEF | 推荐选有权使用的 Nikon Z6 III HE/HE★ 样片，可同时补 R3 格式覆盖；记录新文件大小、来源、授权和 SHA-256。更新引用样片哈希的未来文档与脚本配置，历史验收只加关联说明，不能把旧哈希替换成新哈希。使用新样片另行重跑受影响 A3/A6/A10/A13 等导入、登记、重复与适配器验收，并评估 A7–A9、A12 和 R1/R2 依赖；产生独立新证据，不能把旧结果套到新样片。 |
| (c) 移除仓库中的样片引用 | 原证据依赖样片哈希、来源与结果，删除或改写会损害证明；建议停止未来使用并对历史证据加许可与停用注释，保留原哈希和证据，不声称历史未使用该样片。 |

建议后续选择 (b)，并对既有证据补 (a) 式来源、冲突及署名说明；由用户决定，许可问题不能靠提案单方面解决。

## 工作量、风险与复核命令

工作量为粗略估计：清点与规则/脚本及 dry-run 审阅约 1–2 人日，映射、证据引用核查、格式验证和测试约 1–2 人日；嵌套 JSON、脚本守卫、审批摘要及并发变更可能增加时间。样片替换和 Mac 实机重跑另计，取决于用户提供素材、设备及授权；无实机成功承诺。主要风险是转义漏检、JSON 格式或可运行性变化、可关联的短哈希、历史暴露、误将脱敏证据当原件，以及许可冲突未决。

下列只读命令以基线 checkout 的 tracked 文件为范围；输出可能包含敏感标识，限受控环境，UUID/秘密不应复制到公开报告。`rg -c` 是行数；`rg -o` 每次匹配单独一行，`wc -l` 是出现次数。文件名清单用 `rg -l`；各目录小计可按路径前两段分组。样片哈希搜索列文件而不输出内容。检查后别把私有结果提交。命令中的 UUID 通用模式会匹配会话等 ID，须按上下文人工分类；真实卷分别用本地原始清单中的完整 UUID 作为 `PATTERN`，禁止粘贴到提案，采用同样 `rg -l` / `rg -o` 计数。


```bash
git rev-parse HEAD
git ls-files | wc -l
git ls-files -z | xargs -0 rg -l -F '<HOME>'
git ls-files -z | xargs -0 rg -c -F '<HOME>' | awk -F: '{s+=$NF; n++} END {print "files",n,"matching lines",s}'
git ls-files -z | xargs -0 rg -o --no-filename -F '<HOME>' | wc -l
git ls-files -z | xargs -0 rg -o -F '<HOME>' | cut -d: -f1 | sort | uniq -c
git ls-files -z | xargs -0 rg -l -F '/Volumes/NIKON Z6_3'
git ls-files -z | xargs -0 rg -o --no-filename -F '/Volumes/NIKON Z6_3' | wc -l
git ls-files -z | xargs -0 rg -l -F '/Volumes/Cetacea Studio'
git ls-files -z | xargs -0 rg -o --no-filename -F '/Volumes/Cetacea Studio' | wc -l
git ls-files -z | xargs -0 rg -l -F 'Ludger Heide'
git ls-files -z | xargs -0 rg -o --no-filename -F 'Ludger Heide' | wc -l
git ls-files -z | xargs -0 rg -l -i '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
git ls-files -z | xargs -0 rg -o -i --no-filename '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | sort | uniq -c
git ls-files -z | xargs -0 rg -l -i 'hostname|host_name|computername|localhostname|\.local\b'
git ls-files -z | xargs -0 rg -l -i 'token|api[_-]?key|secret'
git ls-files -z | xargs -0 rg -l -F '\u5de5'
git ls-files -z | xargs -0 rg -l -F '\\u5de5'
git ls-files | rg -i '\.(nef|jpe?g|raw)$'
git ls-files -z | xargs -0 rg -l -F '8ca94584578b35a422744c1a610174ce37df0691588edfdecaec3111b3fbbb02'
```

对各 UUID 和其他字面量的每文件出现次数，将上述 `rg -o --no-filename` 改为 `rg -o` 保留文件名前缀，再按文件分组计数；`rg -c` 不能替代。卷 UUID 前缀在本地对大写完整值执行 `hashlib.sha256(value.upper().encode('utf-8')).hexdigest()[:16]`，报告仅显示前 8 位和摘要前 16 位。secret scan 的命中只列文件、在受控环境人工检查，不能输出值。

## 用户决策（均未选择）

| 决策 | 选择 |
|---|---|
| 当前树脱敏并另建提交 | ☐ 批准　☐ 暂不批准 |
| 替代方案：私有仓库保留标识 | ☐ 接受　☐ 不接受　☐ 待确认仓库权限 |
| 历史处理（本提案不实施） | ☐ 保留历史　☐ 另行评估并授权历史改写或新仓库 |
| 样片许可 | ☐ (a) 保留并署名、继续核实　☐ (b) 后续换用户自摄并为旧证据署名　☐ (c) 停用并注释历史引用　☐ 其他 |
| 数据流 | ☐ 确认：2026-11-02 用户接受 DeepSeek 接收 ID、文件名、哈希、状态等及 `photo_list_sources` 的来源绝对路径；现有工具不发送像素或文件字节。未来内容/缩略图工具或保留条款变化需重新决定。 |
| 真实客户数据 | ☐ GO　☐ NO-GO　☐ 等待上述问题及其他验收关闭；此处选择不替代具体操作授权。 |

