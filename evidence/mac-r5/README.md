# R5 样本替换与脱敏

R5 完成样本替换，并对当前工作树中的个人主目录路径及指定卷 UUID 进行事后脱敏。运行 `python scripts/r5_desensitize.py` 可预览，运行 `python scripts/r5_desensitize.py --check` 可检查残留；映射文件 `evidence/mac-r5/desensitization-map.json` 由 `--apply` 生成。

限制：Git 历史未重写；harness UUID、卷名和项目文件夹名经所有者于 2026-11-03 决定保留；仓库公开，不重写历史。历史 A 系列证据中旧公开样本的 SHA-256、内嵌第三方版权文字和 `cameraSerialNumber` 回读中的第三方相机序列号保持不变，以记录实际运行情况；该样本文件本身从未提交。卷名称（如相机卡默认标签和测试目标名称）作为非识别信息保留。脱敏计划的原有 `plan_digest` 无法重新验证。
