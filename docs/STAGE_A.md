# Stage A / Gate 1

已完成且测试通过: registered resource administration, SQLite state and audit, ingest planning/approval/execution, cancellation/retry/recovery, CLI, and ingest acceptance tests.

Install offline with `.venv/bin/pip install -e . --no-deps --no-build-isolation --no-index` after installing setuptools if needed. The installed environment has mcp 2.3.0 (pinned), Pillow 13.0.0 and pytest 9.2.0.

Example:
```
cetacea init --home /tmp/cetacea-home --library /tmp/cetacea-library --preview /tmp/cetacea-preview
cetacea --home /tmp/cetacea-home source add card /path/to/card
cetacea --home /tmp/cetacea-home order create order1 "Order 1"
cetacea --home /tmp/cetacea-home photographer add p1 "Photographer"
cetacea --home /tmp/cetacea-home plan order1 p1 card --json
cetacea --home /tmp/cetacea-home approve TASK_ID PLAN_DIGEST
cetacea --home /tmp/cetacea-home execute TASK_ID --json
```

Stages default to ingest for Gate 1. Explicit Lightroom/preview stages persist a failed step and raise NotImplementedError. MCP, Lightroom adapters, preview packages and reporting are 尚未开发. No network calls are needed.

Manifest filenames allocate the next available batch run number using atomic hard-link publication, because distinct tasks can target the same batch; events retain the actual task run number. Existing manifests are never overwritten. See KNOWN_RISKS.md for validation history and filesystem fallback limitations.
