# 完整计划与一次审批

此前真实模型调用 `photo_plan_import` 时未传 `stages`。core 的默认值是 `['ingest']`，所以获批准的计划只有导片；随后调用 `lightroom_import_verified` 时，因阶段不在已批准计划中而返回 `PERMISSION_DENIED`。这是正确的检查，仍然保留；原因不是 AI 缺少 Lightroom scope，AI 有该 scope，但始终没有 approve 权限。

现在 MCP 的 `photo_plan_import` 在省略 `stages` 且提供 `preset_id` 时生成完整计划：

```text
计划（ingest → lr_register → lr_preset → lr_export → preview_verify）
  → WAITING_APPROVAL，报告 task_id + plan_digest
  → 人工 CLI 批准一次
  → photo_execute_import 执行全部已批准阶段 → 预览核验
```

省略 `stages` 又未提供 `preset_id` 返回 `INVALID_ARGUMENT`；仅导片请显式传 `stages=['ingest']`。直接调用 core 或 CLI 的默认值仍为 `['ingest']`。含 Lightroom 阶段的计划保存 `lightroom` 快照，包含预设定义及导出 `max_edge`、`quality`、`preview_root`、`library_root`，并计入 `plan_digest`。

`execute` 和 `execute_lightroom` 先重新核验审批记录，再重新计算 `plan_json` 的摘要；计划变化时拒绝并报告 `plan changed after approval`，实时配置与快照不一致时拒绝并报告 `preset/export settings changed after approval`。`photo_execute_import` 可恢复执行，跳过已完成阶段；`lightroom_*` 工具仍可用于单阶段恢复，`photo_retry_task` 可恢复 FAILED 任务而无需重新审批。即使任务已 COMPLETED，重新执行仍检查审批和快照；完成后改变配置会得到 `PERMISSION_DENIED`，而非直接无操作返回，这是可接受的当前行为。

Linux 上的真实 DeepSeek 检查使用 `deepseek-flash`、thinking 关闭：1 个场景、两轮各 4 次真实请求（共 8 次，上限 12）。模型传了 `preset_id`、未传 `stages`，生成五阶段计划并等待审批；人工批准一次后，模型调用 `get_task`、`photo_execute_import`、`list_assets`、`verify_preview`，最终 COMPLETED、预览核验 OK、1 条审批记录、无 `PERMISSION_DENIED`。证据在 `evidence/fullplan/`。这只是非确定性模型的一次采样，Lightroom 为 **MOCK**，不构成可靠性或真实 Lightroom/macOS 验证。
