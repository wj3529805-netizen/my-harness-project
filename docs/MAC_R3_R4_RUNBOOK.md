# Mac R3 / R4 测试文件夹验证

仅使用用户指定的测试素材与独立测试目标，不使用生产目录、NAS 或生产 Lightroom catalog。卡上测试文件夹的名称会按设计以相对路径出现在证据中；其他卡上内容不在范围内，脚本不会列出、哈希或记录这些内容。结果只覆盖所选文件夹，并非 ROADMAP 中的整卡验证；本准备工作没有在 macOS 或真实卡上验证。

先在卡的一个文件夹中拍摄若干 Nikon Z6 III NEF，分别使用 HE 和 HE★ 模式。缺少任一种时 R3 标记 `NOT_COVERED`，退出码非零。脚本只导入该文件夹内的 NEF，但会清点该文件夹的其他普通文件；不要把客户素材放入此文件夹。准备足够大的 NEF，确保能观察到进行中的复制（建议数百 MB）。不要用 Finder 修改卡。

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

拔卡恢复（运行时保持目标卷连接）：

```sh
.venv/bin/python scripts/mac/r4_unplug.py --source-uuid '<CARD_UUID>' --source-subdir 'DCIM/142NZ6_3' --target-base '<TEST_TARGET_BASE>' --out 'evidence/mac-r4/run-<YYYYMMDD-HHMM>' --confirm-card-readonly --scenario unplug --inter-file-delay 3
```

审批后等待 `NOW PULL THE CARD`，再拔出卡；出现 `REINSERT THE SAME CARD` 后重新插入同一张卡。必须恢复到原挂载点，否则停止。没有观察到复制增长时会报告 `INTERRUPTION_NOT_ACHIEVED`，应换用更大的测试文件。恢复需等待原租约到期，默认最多 1200 秒。

人工拔卡建议使用 `--inter-file-delay 3`，它在每个文件提交后等待三秒，方便操作，但拔卡可能发生在文件之间而非文件复制中。观察 `.part` 要求复制正在进行；观察步骤只有在看到 `.part` 增长后才提示拔卡。`after-interruption-files.json` 的 `parts` 记录中断时是否存在 `.part`，应结合该记录解读结果，不能把文件间拔卡说成文件复制中断。

进程强杀场景不需要拔卡：

```sh
.venv/bin/python scripts/mac/r4_unplug.py --source-uuid '<CARD_UUID>' --source-subdir 'DCIM/142NZ6_3' --target-base '<TEST_TARGET_BASE>' --out 'evidence/mac-r4/run-<YYYYMMDD-HHMM>' --confirm-card-readonly --scenario kill-process
```

它仅验证进程被杀后的恢复，不能代表物理拔卡或断电；真实断电不在本脚本范围。可选 `--max-files N` 限制导入的 NEF 数量，`--inter-file-delay 1` 在子进程每个文件提交后等待一秒，并不能减慢文件内部复制。

证据分别位于 `evidence/mac-r3/`、`evidence/mac-r4/` 的运行目录中，包括范围声明、清点、计划、审批、读回和结果；检查 `result.json`，不要将失败或未覆盖说成通过。提交的证据目录只能包含脱敏后的输出；提交前检查结果，切勿提交真实 UUID、用户名、绝对挂载路径、原始照片、临时 home、日志或目标文件。R3 的 HE/HE★ 判定由纯 Python MakerNote 解析产生，不依赖 exiftool；无法识别的值保留原始数字并标记 UNKNOWN。

证据文件采用不覆盖写入；重复运行前请用 `--out` 指定新的证据目录。`--lightroom real` 当前会明确拒绝运行，尚未实现真实测试 catalog 守卫。
