# Mac R3 / R4 测试文件夹验证

真实 Lightroom 的 R3+LR 已准备但尚未在 Mac 运行（NOT_RUN）；R4+LR 已推迟（NOT_RUN）。见 [R6 手册](MAC_R6_RUNBOOK.md)。

## HE / HE★ 判别依据

MakerNote `0x0051` 偏移 10 的值：13 为 HE，14 为 HE★，3 为 Lossless；已用有标签的公开 Z8/Z9 样片核对。原始 strip 的恒定码率可独立佐证：HE 为 3.0 bpp，HE★ 为 5.0 bpp。两项冲突时标记 UNKNOWN，仅有码率时不分类。

Z6III 帧若 `0x0051=14` 且为 5.0 bpp，即使用户认为拍的是 HE，仍判为 HE★；请检查相机菜单「照片拍摄菜单 > RAW 记录」并重拍一帧。Z6III 的 HE 应显示 13，6064×4040 图像的 strip 预计约 9,186,960 字节（6064×4040×3/8）。已用 `samples/Nikon-Z6III-HE-DSC_9725.NEF` 确认 Z6III HE（无星）：标签值 13、3.0 bpp。

仅使用用户指定的测试素材与独立测试目标，不使用生产目录、NAS 或生产 Lightroom catalog。卡上测试文件夹的名称会按设计以相对路径出现在证据中；其他卡上内容不在范围内，脚本不会列出、哈希或记录这些内容。结果只覆盖所选文件夹，并非 ROADMAP 中的整卡验证；本准备工作没有在 macOS 或真实卡上验证。

先在卡的一个文件夹中拍摄若干 Nikon Z6 III NEF，分别使用 HE 和 HE★ 模式。缺少任一种时 R3 标记 `NOT_COVERED`，退出码非零。脚本只导入该文件夹内的 NEF，但会清点该文件夹的其他普通文件；不要把客户素材放入此文件夹。R4 可使用测试限速来观察普通大小 NEF 的复制过程。不要用 Finder 修改卡。

在 Mac 本地查找卡的 UUID（不要把输出或真实 UUID 提交）：

```sh
diskutil info -plist /Volumes/NAME
diskutil info /Volumes/NAME | grep UUID
```

将下面占位符换成用户指定的值。目标为另一块卷上的测试目录，脚本会创建全新的运行目录；默认目标基目录 `/Volumes/Cetacea Studio` 必须已挂载，否则用 `--target-base` 指定已挂载的目标目录。`--home` 省略时使用本地新建临时目录。每次运行都必须用 `--out` 指定全新的证据目录，例如 `--out evidence/mac-r3/run-<YYYYMMDD-HHMM>`；R4 同样使用独立的新目录。安装项目依赖后，在仓库根目录先执行 `source .venv/bin/activate`，让脚本打印的 `python` 审批命令使用同一环境，然后运行：

```sh
.venv/bin/python scripts/mac/r3_fullcard.py --source-uuid '<CARD_UUID>' --source-subdir 'DCIM/142NZ6_3' --target-base '<TEST_TARGET_BASE>' --out 'evidence/mac-r3/run-<YYYYMMDD-HHMM>' --confirm-card-readonly
```

查看终端打印的文件数、字节数、任务 ID 和摘要，在另一个终端运行脚本打印的完整 `python -m cetacea.cli --home ... approve ...` 命令。审批必须由人执行，切勿复制真实路径或 UUID 到证据仓库。R3 除插卡、运行及审批外无需操作；当前运行仅执行导入，不执行任何 Lightroom 阶段（包括模拟和真实阶段）。

### 另一张卡 / USB 读卡器的限量 R3

使用另一张卡和 USB 读卡器时，必须按 Volume UUID 选择源卡；两张卷都名为 `NIKON Z6_3` 时不能仅凭卷名判断。先在本机用只读的 `diskutil list` 找到各卷的设备标识，再分别运行 `diskutil info -plist <DEVICE_IDENTIFIER>`，核对 `VolumeUUID`、`MountPoint` 和 `BusProtocol`（文本版 `diskutil info` 显示为 `Protocol`）。不要把 USB 卡 UUID 与内建 SD 插槽中卡的 UUID 混淆，也不要提交这些原始输出。

由人确认源卡与 Studio 目标 UUID 后，使用新的证据目录运行：

```sh
.venv/bin/python scripts/mac/r3_fullcard.py --source-uuid '<USB_CARD_UUID>' --source-subdir DCIM/142NZ6_3 --max-files 12 --target-volume-uuid '<STUDIO_UUID>' --out 'evidence/mac-r3/other-card-<YYYYMMDD-HHMM>' --confirm-card-readonly
```

`--max-files 12` 将计划和导入限制为最多 12 个 NEF；清点和源卡前后对比仍可覆盖整个指定文件夹。卡全程只读，Studio 保持连接，此项不做目标盘拔出测试。结果记录实际读取的 `source_protocol` 与 `max_files`；这些字段和本地合成测试本身不构成另一张实体卡 / USB 读卡器通过的证据，须等待人工实体运行及读回核验。

拔卡恢复（运行时保持目标卷连接）：

```sh
.venv/bin/python -u scripts/mac/r4_unplug.py --source-uuid '<CARD_UUID>' --source-subdir 'DCIM/142NZ6_3' --target-base "$PWD/acceptance-data/r4-target" --confirm-card-readonly --scenario unplug --throttle-mbps 3 --hold-mid-file --max-files 8 --pull-timeout 600 --reinsert-timeout 1800 --out evidence/mac-r4/run-<ts>
```

审批后，测试脚本会人为在首个文件的复制中途暂停；只有暂停已经生效时才显示 `NOW PULL THE CARD`。拔卡或 600 秒超时后继续读取；拔卡后的读取错误是真实的。出现 `REINSERT THE SAME CARD` 后重新插入同一张卡，必须恢复到原挂载点。`HOLD_TIMEOUT` 表示没有及时拔卡，没有伪造中断；请使用新的 `--out` 重新运行。首个文件不超过 1 MiB 时不会暂停。`--hold-mid-file` 需要 `--throttle-mbps`，支持 `unplug` 和 `target-unplug` 场景，`--pull-timeout` 最多 3000 秒。

限速由测试脚本人为施加，吞吐量不能代表产品速度。执行租约每个文件开始时更新为 300 秒；较长的暂停可能使租约在子进程仍运行时到期。脚本只在中断后子进程退出时调用恢复，FAILED/PAUSED 任务仍按原流程恢复。恢复默认最多等待 1200 秒。

`--inter-file-delay` 仅在文件提交之间暂停，暂停期间没有 `.part`，单独使用不能创造文件复制中断窗口，也不能触发拔卡提示；仅建议与 `--throttle-mbps` 配合，通常不需要。`after-interruption-files.json` 的 `parts` 和 `result.json` 的 `part_in_progress_at_interruption` 及大小记录中断时的临时文件情况，不能把文件间拔卡说成文件复制中断。

出现提示时证据目录分别保留 `PULL_NOW` 和 `REINSERT_NOW` 标记，内容包括时间、任务 ID、观察到的临时文件大小和是否暂停。这些标记很小，可以提交，用于记录提示时机。

进程强杀场景不需要拔卡：

```sh
.venv/bin/python scripts/mac/r4_unplug.py --source-uuid '<CARD_UUID>' --source-subdir 'DCIM/142NZ6_3' --target-base '<TEST_TARGET_BASE>' --out 'evidence/mac-r4/run-<YYYYMMDD-HHMM>' --confirm-card-readonly --scenario kill-process
```

它仅验证进程被杀后的恢复，不能代表物理拔卡或断电；真实断电不在本脚本范围。可选 `--max-files N` 限制导入的 NEF 数量，`--inter-file-delay 1` 在子进程每个文件提交后等待一秒，并不能减慢文件内部复制。

证据分别位于 `evidence/mac-r3/`、`evidence/mac-r4/` 的运行目录中，包括范围声明、清点、计划、审批、读回和结果；检查 `result.json`，不要将失败或未覆盖说成通过。提交的证据目录只能包含脱敏后的输出；提交前检查结果，切勿提交真实 UUID、用户名、绝对挂载路径、原始照片、临时 home、日志或目标文件。R3 的 HE/HE★ 判定由纯 Python MakerNote 解析产生，不依赖 exiftool；无法识别的值保留原始数字并标记 UNKNOWN。

证据文件采用不覆盖写入；重复运行前请用 `--out` 指定新的证据目录。`--lightroom real` 当前会明确拒绝运行，尚未实现真实测试 catalog 守卫。

`result.json`、`plan.json` 和 README 记录暂停释放时的 `part_size_at_removal`（子进程在恢复读取前记录）、`part_in_progress_at_interruption`，以及失败后的 `parts_after_failure`。`hold-state.json` 保存暂停时间和大小。`held_file_rel`、`first_failed_file`、`first_failed_error_class`、`failed_file_count`、`held_file_failed_first` 和 `child_exit_code` 用于核对首个文件确实在中途失败；`simulated_by_test` 标记仅供测试的模拟。拔卡后后续文件可能在打开时报告 ENOENT，因为卡已不在；相关情况记录在 `later_files_failed_because_card_absent`。恢复成功但中断证据不足时结果为 `FAIL_UNVERIFIED_INTERRUPTION`。

接近自然复制速度的拔卡测试可使用轻度限速（例如 `--throttle-mbps 30`，不加 `--hold-mid-file`），在 `PULL_NOW` 后拔卡；脚本轮询记录拔卡前后的 `.part` 大小，只有观察到未完成的临时文件才能验证文件复制中断。重新插入后仍须由卷 UUID 确认同一张卡且恢复到原挂载路径；macOS 重新挂载时 `st_dev` 可能变化，结果中的前后设备号及变化标记仅用于诊断。

目标盘断开测试使用 `--scenario target-unplug --throttle-mbps 3 --hold-mid-file --target-volume-uuid '<TARGET_UUID>'`（其余源卡与只读确认参数同上）；`home` 和证据目录必须位于目标卷之外。hold 会在首个文件仍为部分 `.part` 时暂停，监测目标卷的 UUID、挂载状态和设备号是否消失或变化，源卡全程保持挂载。只有已观察到增长的 `.part`、子进程仍存活、提示当下仍有 `0 < size < expected` 的 `.part`，且所选 hold 已生效，才写入 `TARGET_UNPLUG_NOW` 并显示 `NOW UNPLUG THE TARGET VOLUME`。看到此提示后拔目标盘，看到 `TARGET_REINSERT_NOW` / `RECONNECT THE SAME TARGET VOLUME` 后接回同一目标卷。可省略 hold 并使用轻度限速，但提示仍须满足存活与部分文件检查。

提示前子进程失败时结果为 `FAIL_STOPPED`，证据保留 `child.log` 输出、任务错误和首个 FAILED 文件错误；不会发出目标盘拔出或接回标记，也不会进入拔盘后的恢复重试流程。即使恢复重试为 `COMPLETED`，缺少 `part_in_progress_at_interruption` 仍不能 PASS；hold 场景还须通过 `hold_verdict` 的中断核验。此测试验证目标卷断开，不测试 Mac 交流电源断电。

目标卷断开后可能无法读取 `.part` 大小；hold 仅在暂停开始大小与提示前实时大小一致、且因目标消失释放时，使用已保存的暂停证据，标记 `part_evidence_source=held_at_cue_before_target_removal`。缺少此证据或暂停已超时仍不能 PASS。
