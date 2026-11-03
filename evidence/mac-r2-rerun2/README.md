
<!-- R5-DESENSITIZATION-START -->
2026-11-03 R5 事后脱敏：主目录路径替换为 `<HOME>`，卷 UUID 替换为 `<VOLUME_UUID:...>`。原文件哈希和 plan digest 未重新计算。详见 `evidence/mac-r5/desensitization-map.json` 和 `docs/R5_CLEANUP_PROPOSAL.md`。

R5 post-hoc redaction on 2026-11-03 replaced home paths with `<HOME>` and volume UUIDs with `<VOLUME_UUID:...>`. Original file hashes and plan digests were not recomputed. See `evidence/mac-r5/desensitization-map.json` and `docs/R5_CLEANUP_PROPOSAL.md`. Scripts in this directory that had literal volume UUID guards contain placeholders and are no longer runnable as-is; they are retained as historical records.
本目录中原含卷 UUID 字面量检查的脚本因占位符不能直接运行，保留作为历史记录。
<!-- R5-DESENSITIZATION-END -->
