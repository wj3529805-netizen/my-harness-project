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
