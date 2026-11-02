# Gate 1 validation notes

- Initial editable install failed because the venv lacked setuptools. Installed the bundled `/usr/share/python-wheels/setuptools-78.1.1-py3-none-any.whl` offline; editable installation then succeeded.
- Initial unscoped pytest discovery collected the unrelated third_party-review DeepSeek SDK suite and failed with 21 missing-module collection errors. Project discovery is explicitly `tests/`, as specified by this project's layout. Those third-party tests were not changed or deleted.
- Lightroom, preview, MCP and reports are 尚未开发 in Stage A. No real Lightroom/macOS verification is claimed.
- First project acceptance run: 51 passed, one identity-conflict test failed because manifest temp parent was missing, masking IDENTITY_CONFLICT. Fixed parent creation; assertion retained.
- Second run: same test caught an existing batch manifest from another task's run 1. Manifest allocation now retries the next batch manifest number atomically without overwriting; task run remains in each event.
- Hard-link fallback: for unsupported-link errors, the engine acquires an exclusive per-destination `.cetacea-lock`, checks nonexistence again, and renames. This coordinates CETACEA writers; external writers that ignore the lock can race the rename. Prefer filesystems supporting hard links. Own fallback lock files are removed after release.

Final Gate 1 validation: `.venv/bin/python -m pytest -q` — 59 passed. No project test remains failing. All earlier failures above are retained as validation history.
- Commit attempt (`git add -A && git commit -m "feat(stage A): implement verified ingest workbench and Gate 1 acceptance tests"`) was blocked by the environment: `.git/index.lock` cannot be created because `.git` is read-only. Code remains uncommitted on phase1; no push attempted.

Stage B validation history: first full run was 57 passed, 2 failed. The failures exposed a missing human Lightroom scope and an ingest completion check that treated cooperative cancellation as full ingest completion. Fixed the scope and require all assets VERIFIED before skipping a completed ingest step; original assertions retained.

Stage C validation history:
- First full run: 65 passed, 1 failed (`test_real_mcp_interface_only`): fake stdio server initialization timed out in the existing real adapter. Investigating with the installed MCP 2.3.0 source; no assertions removed or weakened.

---
# 已知风险与未完成事项（Phase 1 收尾）

测试：全量 `pytest` 71 passed（Linux，Python 3.13，2026-10-30）。没有保留的失败测试。开发过程中的失败与修复历史见上文。

1. **未在 macOS / 真实 Lightroom 上验证**任何东西。`RealLightroomMcpAdapter` 只对假 MCP 服务器做过接口测试；lightroom-mcp 实际返回格式（import_photos 无 photo id、export_photos 无文件名）按源码阅读做的假设，须在 Mac 上验收清单 A13 确认。
2. 真实适配器每次调用都启动一个 MCP 子进程（简单、隔离，但慢）；大批量时需改为长连接会话。
3. Mock 适配器的“已登记”状态在进程内存里；跨进程时以数据库 assets.lr_photo_id 为准。
4. 硬链接不可用时的回退（`.cetacea-lock` + rename）只对遵守锁的 CETACEA 写入者安全；外部写入者可能竞争。APFS 支持硬链接；exFAT/SMB 待验证。
5. 性能：扫描一次完整哈希，复制时再读源、读回临时文件、最终读回，共约 4 次读取；大卡（数百 GB）耗时较长，未做基准测试。
6. `photo_list_sources` 会向 AI 返回已登记来源的绝对路径（只读信息，AI 不能据此读写任意路径）。
7. 磁盘满/权限错误通过故障注入和 monkeypatch 测试，并非真实磁盘满。
8. 没有真实 AI 客户端（Codex/Claude/Harness）联调；MCP 测试使用 SDK 的 stdio 客户端。Harness 需要 Node ≥ 24.9。
9. 私有 GitHub 仓库未能核查（需 GitHub App 授权）。
10. 无 Windows 支持；POSIX 专用调用（O_NOFOLLOW、os.link）。
11. 代码风格偏紧凑（Codex 生成），后续可重构；测试覆盖了行为但未做覆盖率统计。
12. 开发流程说明：Codex 因 `.git` 沙箱只读无法提交；提交由编排者完成。Codex 在 Stage B/C 两次卡在调试 mcp 2.x stdio 细节时被中止，编排者**直接修改了**：tests/fake_lightroom_mcp.py（改用 `server.run()`）、real_mcp.py（客户端结果字段为 snake_case：`is_error`、`structured_content`）、tests/test_mcp.py（audit_log 列名 actor）、report.py（丰富 Markdown 报告）。
13. CLI: 未批准就 execute 会输出 Python 堆栈（NotApproved）而不是友好提示；已被拒绝，功能正确，仅体验问题。

## macOS validation update — 2026-11-02

详见 [MACOS_VALIDATION.md](MACOS_VALIDATION.md) 和 evidence/mac-acceptance/。基线 macOS 71/71；本次修复和新增回归后 98/98，真实独立 Lightroom catalog 的公开 Nikon Z6 NEF 登记、预设、导出、缺失检测、重复请求、批次关闭/恢复通过。先前“未做任何 macOS/真实 Lightroom 验证”的文字是开发期历史，不能再用来描述本次样本范围。

本次新增失败历史：Bash 3.2 中文括号变量解析失败；第一版合成 DNG 被 Adobe 以 dng_error_unsupported_raw 拒绝；全局禁用硬链接的新回归揭示清单不支持回退，随后导出恢复新回归揭示 SQLite state="FAILED" 与 failed 列冲突；慢调用回归在旧 300 秒租期下暴露 recover 可夺走活任务。上述产品问题已修并保留回归。真实调用的底层错误现不会仅剩 TaskGroup 摘要。无硬链接的锁回退仍有不守锁外部写入者 race。

实体卡/读卡器、真实外置 exFAT/SMB、实际 AI 产品客户端（可选 A14）、Z6 III HE/HE★、断电/强杀以及 Windows 仍未通过实机验收。A12 关闭点在两张照片之间，不能当作单次 catalog 写入中断证明。样片发行 README 与内嵌版权许可文字有差异，保留来源及作者信息，照片和预览不随 Git 发布。已知 CLI NotApproved 堆栈体验问题仍在。
