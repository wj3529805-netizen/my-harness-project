# CETACEA Photo Workbench — Phase 1 SPEC (acceptance first)

Language: Python 3.13, stdlib + `mcp` (2.x) + `pillow`. No other runtime deps. Package: `src/cetacea/`. Tests: `tests/`. Install: `.venv/bin/pip install -e .` (pyproject.toml, console script `cetacea`).

## Layout
```
src/cetacea/
  config.py        # Home dir (state dir) + registered resources: sources, library root, preview root, presets
  db.py            # SQLite (WAL, foreign_keys), schema + migrations (user_version), short-lived connections
  core.py          # Workbench service class = the ONLY business API; CLI and MCP both call it
  perms.py         # Principal(actor_type human|ai, actor_id, scopes); require(scope); ai can never hold `approve`
  audit.py         # audit_log writes (actor, action, task_id, detail JSON, ts)
  ingest/pathsafe.py scanner.py copier.py manifest.py
  tasks.py         # state machine + stage runner
  lightroom/base.py mock.py real_mcp.py
  preview.py       # preview package mapping + verification
  report.py        # JSON + Markdown task report
  mcp_server.py    # stdio MCP server (MCPServer)
  cli.py           # argparse CLI `cetacea`
tests/             # pytest, one file per area
scripts/e2e_demo.py
```

## Registered resources (config.json in home dir; created by `cetacea init`)
- `library_root`, `preview_root` (distinct, must not overlap each other or any source).
- `sources`: id -> {label, path, kind: "card"|"folder"}. Tools take `source_id`, never raw paths.
- `presets`: id -> {label, lightroom_uuid|null, lightroom_name}. Tools take `preset_id`.
- Orders and photographers live in the DB (`orders`: order_id, title; `photographers`: photographer_id, name) — created via CLI (human) only.

## Safe ingest (highest priority)
Scanner: walks a registered source root with os.scandir (no following symlinks). Per regular file: rel_path (posix, normalized, no `..`), size, SHA-256 (streamed), kind (raw/jpeg/sidecar/other by extension; RAW ext set incl. raf nef nrw arw cr2 cr3 dng orf rw2 pef srw x3f raw 3fr iiq; jpg/jpeg; xmp/acr sidecar -> kind "sidecar", copied but never modified). Symlinks, devices, fifos are NOT followed/copied; reported in `skipped` with reason. Hidden system files (.DS_Store, Thumbs.db, ._*) skipped with reason. Scan must not modify the source (no atime games needed; just do not write).
Scan result digest = sha256 over sorted (rel_path,size,sha256).

Ingest does not require a RAW/JPEG pair. Every regular file classified as raw (including a standalone NEF) or jpeg (`.jpg` / `.jpeg`, any case) is scanned, planned, and copied whether or not a partner with the same stem exists. A missing partner never drops the file that is present. A mixed batch copies the paired files and the unpaired files. Stem pairing is not consulted by scan, plan, or copy; it applies only later, when a plan includes Lightroom or preview stages. Copying a standalone JPEG into the library does not by itself require sending that JPEG to Lightroom. Verification is unchanged: the destination is re-read and its SHA-256 must match the scan.

Identity: `asset_id = "ast_" + sha256(f"{order_id}\0{photographer_id}\0{batch_id}\0{rel_path}\0{sha256}")[:24]`. Two photographers with DSC0001.RAF never collide. Batch id: caller-supplied label (`[A-Za-z0-9._-]{1,64}`) or `b_` + scan digest[:12].
Destination: `<library_root>/<order_id>/<photographer_id>/<batch_id>/<rel_path>` (ids validated against `[A-Za-z0-9._-]+`, no leading dot). Validate every component; resolve with realpath and assert it stays inside library_root; refuse if any existing component of the destination chain is a symlink (lstat each); refuse if source root and library root overlap in either direction (realpath).

Copy engine (per file), exactly:
1. open source `O_RDONLY|O_NOFOLLOW`, fstat must be regular file; size/mtime recorded.
2. stream to a temp file `<library_root>/.cetacea-tmp/<task_id>/<n>.part` (created `O_CREAT|O_EXCL|O_WRONLY`, 0600→final mode 0644), computing SHA-256 of bytes read; flush + fsync file.
3. If bytes-read sha != scan sha (source changed since scan/plan) => fail that file `SOURCE_CHANGED`, delete temp.
4. Re-open temp, re-read fully, sha must match (read-back verify of temp). 
5. If final path already exists: hash the EXISTING FILE ON DISK now (never trust DB/size/name). equal => `skipped_verified` (count as success, no write). different => `CONFLICT` (no overwrite, temp deleted, file reported, task will end FAILED with conflict list).
6. Else atomic no-overwrite commit: `os.link(temp, final)` (fails with FileExistsError if it appeared concurrently => go to step 5 logic), then unlink temp; fsync parent dir. If hardlinks unsupported on the FS => fall back to `os.rename` ONLY after re-checking non-existence under a per-destination lock file `O_EXCL`; document it.
7. Re-read the committed final file, sha must equal scan sha => asset status VERIFIED. (Final read-back is mandatory.)
Errors: ENOSPC/EDQUOT/EACCES/EIO/OSError per file => that file FAILED with errno name + message, temp removed, loop continues or stops per `stop_on_error` (default: stop on ENOSPC, continue otherwise). Preflight free-space check (`shutil.disk_usage`, injectable for tests) against total bytes to copy + 1% margin => task FAILED `INSUFFICIENT_SPACE` before any copy.
Interruption/resume: files already VERIFIED are re-verified by re-hashing the on-disk target and skipped; stale `.part` files for the task are removed on resume; a second run never duplicates or overwrites. A fault-injection hook (`fault_hook(stage, rel_path)` that may raise) must exist on the engine for tests (stages: after_temp_write, before_commit, after_commit).
Never: delete/modify/chmod anything in the source; delete anything in the library except own `.part` temp files.
Manifest: `<batch_dir>/.cetacea/import-manifest-run<N>.json` written atomically with no overwrite (rel_path, size, sha256, asset_id, status, verified_at, order, photographer, batch, source_id, run). Run log: JSONL at `<home>/logs/<task_id>.jsonl` (append only, every file event).

## Photo Core (SQLite)
Tables: orders, photographers, batches(batch_id, order_id, photographer_id, source_id, scan_digest), assets(asset_id PK, order_id, photographer_id, batch_id, rel_path, size, sha256, kind, status PLANNED|COPYING|VERIFIED|CONFLICT|FAILED|SKIPPED, error, dest_rel_path, lr_photo_id, lr_status, preset_applied, mock INT), tasks(task_id, idempotency_key UNIQUE, type, state, order_id, photographer_id, batch_id, source_id, plan_json, plan_digest, stages_json, run_count, error, created_at, updated_at), task_steps(task_id, run, stage, state, succeeded, failed, skipped, detail_json, started_at, ended_at), approvals(task_id, plan_digest, approved_by, scopes, granted_at, revoked_at), previews(preview_id, task_id, run, asset_id, path, sha256, width, height, status, mock), audit_log.
Same asset_id must never be inserted twice; same (order,photographer,batch,rel_path) with a different sha256 => `IDENTITY_CONFLICT` (recorded; never overwritten).

## Task state machine
States: PENDING, WAITING_APPROVAL, RUNNING, PAUSED, COMPLETED, FAILED, CANCELLED. Explicit transition table; illegal transition raises `InvalidTransition` and is audited.
- `plan_import(order, photographer, source_id, batch label?, preset_id?, stages=[ingest, lr_register, lr_preset, lr_export, preview_verify] subset, scan result)` -> task PENDING -> WAITING_APPROVAL, with `plan_json` (file list, totals, destination, stages) and `plan_digest`. Idempotent: idempotency_key = sha256(order, photographer, source_id, batch_id, scan_digest, preset_id, stages) — same request returns the SAME task id, no new rows (duplicate submit / AI repeats call).
- `approve(task_id, plan_digest)` — human principal only (scope `approve`); must pass the exact current plan_digest; records approval. AI principals can never approve (perms.py hard rule).
- `execute(task_id)` — scope `execute`; refuses (PermissionDenied/NotApproved) unless a non-revoked approval matching plan_digest exists. Runs stages in order; each stage persists a task_step row with succeeded/failed/skipped counts and detail. Completed stages are not redone (already VERIFIED assets are re-hash-verified only). Stage failure => task FAILED (approval kept, so `retry` can resume). Running an already COMPLETED task returns the stored result (idempotent, no work). Execute on a task in RUNNING by another live runner => refuse (use a DB row lock/lease with timeout).
- `cancel(task_id)` — allowed from PENDING/WAITING_APPROVAL/RUNNING/PAUSED; cooperative: checked between files; revokes approval; state CANCELLED; partial copied+verified files stay (never deleted).
- `retry(task_id)` — from FAILED: back to RUNNING via execute path (approval retained); from CANCELLED: -> WAITING_APPROVAL requiring a fresh approval; increments run_count; only unfinished/failed assets are processed.
- Crash recovery: `recover()` marks tasks left RUNNING with an expired lease as PAUSED; resume via `execute`.
- Every state change + tool call is audited with actor.

## Lightroom adapter
`LightroomAdapter` ABC (lightroom/base.py): `status()`, `register(files: list[VerifiedFile]) -> list[RegisterResult]`, `apply_preset(photo_refs, preset) -> list[PresetResult]`, `export_jpeg(photo_refs, dest_dir, max_edge, quality) -> list[ExportResult]` (per-photo result incl. output path or error; adapters must report per-photo outputs). VerifiedFile = {asset_id, abs_path in library, sha256, size}. Core re-hashes the library file immediately before handing to the adapter and refuses mismatches.
`MockLightroomAdapter`: pure-Python, `mock=True`, status says `"MOCK — not real Lightroom"`; ids `mock-lr-<n>`; deterministic; supports injected failures (set of asset_ids or rel_path patterns failing at register/preset/export) to model partial failure; export writes real decodable JPEGs via Pillow (size configurable, default 1200x800, solid/gradient derived from asset hash, text/Exif/comment marker "CETACEA-MOCK asset_id=…"), file named `<order>_<photographer>_<stem>_<asset8>.jpg` into a given NEW dir; never opens .lrcat, never writes XMP/ACR; never touches RAW bytes except reading hash.
`RealLightroomMcpAdapter` (lightroom/real_mcp.py): talks MCP stdio to the Automaat/lightroom-mcp server (command configurable, default `npx -y @mskalski/lightroom-mcp@0.26.0`; env LIGHTROOM_MCP_TOOLSETS=develop, NOT all). HARD allowlist in code of tools it may call: get_selected_photos? NO — only: `import_photos`, `get_photo_metadata`, `apply_develop_preset`, `export_photos`, `list_develop_presets`, `search_photos`. Any other tool name raises. Never calls remove_photos_from_catalog / reset / set_develop_settings / export with on_existing=overwrite. import_photos is called per single verified library file (no copy_to). photo refs = the library file path (lightroom-mcp accepts file paths as photo_ids; confirm via get_photo_metadata). export_photos one photo per call into a fresh empty subdir, `on_existing:"skip"`, then the single resulting file is detected. The stdio child receives `LIGHTROOM_MCP_TOOLSETS=develop`. When `CETACEA_BRIDGE_HOME` is set, that absolute directory is also passed as the child's `HOME`, overriding the session runner's isolated workspace `HOME`; the token file is not read or copied. Not enabled unless config `lightroom.adapter = "real_mcp"`; on Linux it must refuse with a clear "requires macOS Lightroom Classic" unless an explicit test endpoint is given. Tested ONLY against a fake MCP stdio server (tests/fake_lightroom_mcp.py) that mimics tool names/schemas => label "interface-level only, NOT real Lightroom".

## Preview package
Per export run: dir `<preview_root>/<order>/<photographer>/<batch>/<task_id>/run-<N>/` created with exclusive mkdir (existing => new N; never overwrite). Records in `previews` table + `preview-manifest.json` (asset_id <-> source rel_path <-> raw sha256 <-> jpg path <-> jpg sha256 <-> w,h <-> mock flag). `verify_preview(task_id)`: for each VERIFIED asset expected: exists, regular file, decodes fully with Pillow (`load()`), long edge within [min_edge, max_edge] (cfg), JPEG format, sha recorded, mapped to exactly one asset (via DB mapping, NOT by filename), no orphan JPGs in dir, count equal. Report lists `missing`, `failed`, `orphans`, `size_violations`. Status OK only if all clean. RAW+JPG pair mapping: if the source batch has both IMG_1.RAF and IMG_1.JPG in the same relative directory, preview maps to the RAW asset id and records `paired_jpg_asset_id` for that JPEG. The JPEG stays in the library; pairing does not remove it from ingest. A JPEG with no matching raw stays in the later Lightroom/preview asset list. The R6 large-mode acceptance script can exclude standalone JPEGs from Lightroom; that filter is in `scripts/mac/r6_lightroom.py` (`RawLightroomWorkbench`), not in the copy engine. Current core behavior is not a real-Lightroom or macOS acceptance of standalone JPEG.

## MCP server (stdio, `cetacea mcp-serve --home DIR --actor ai:name --scopes read,plan,execute,lightroom,cancel`)
Tools (each calls Workbench with an AI Principal; schema = only IDs): photo_list_orders, photo_list_sources, photo_scan_source(source_id), photo_plan_import(order_id, photographer_id, source_id, batch_label?, preset_id?, stages?), photo_execute_import(task_id), photo_get_task(task_id), photo_cancel_task(task_id), photo_retry_task(task_id), photo_list_assets(task_id|batch_id,...), lightroom_get_status(), lightroom_import_verified(task_id), lightroom_apply_preset(task_id, preset_id), lightroom_export_preview(task_id), photo_verify_preview(task_id). NO tool for approve, no path arguments, no shell, no delete. Errors returned as structured tool errors (code, message), never fake success. Tool results for mock adapter include `"mock": true`.

## CLI (human principal, full scopes incl. approve)
`cetacea init --home H --library L --preview P`, `source add`, `order create`, `photographer add`, `preset add`, `scan`, `plan`, `approve`, `execute`, `task show|list`, `cancel`, `retry`, `assets`, `lr-status`, `verify-preview`, `report`, `recover`, `mcp-serve`. `--json` output option. `--home` or env CETACEA_HOME. CLI `plan` without `--stages` is ingest only. MCP `photo_plan_import` with `preset_id` and omitted `stages` expands to ingest, lr_register, lr_preset, lr_export, and preview_verify; pass `stages=['ingest']` when the request is copy-in only.

## Required pytest scenarios (names must contain the number: test_01_..., etc.). Every test asserts real filesystem/DB state; no weakened assertions.
1 normal import of 10 mock files (mixed RAW/JPG, 2 subdirs) -> all VERIFIED, bytes identical, manifest present, source tree byte-and-mtime identical before/after.
2 same filename in different source subdirs -> two assets, two dest files.
3 two photographers same filename (DSC0001.RAF, different content, same order) -> distinct asset_ids and dest paths, no collision.
4 same rel path & batch, content changed between two imports -> IDENTITY/CONFLICT detected, original untouched, reported, task FAILED.
5 destination already holds the correct file -> skipped_verified, not rewritten (mtime/inode unchanged), counted as skipped.
6 destination holds same-size different-content file (and DB/history claims it matches) -> CONFLICT, not overwritten, not marked verified.
7 interruption mid-copy (fault_hook raises after_temp_write; also before_commit) -> no partial final file, temp cleaned on resume, resume completes, no duplicates.
8 disk full: (a) preflight with injected disk_usage -> INSUFFICIENT_SPACE before copying; (b) ENOSPC raised mid-write -> file FAILED, no final file, temp removed.
9 source read failure (EIO/EACCES on one file via injection or chmod) -> that file FAILED, others per policy, source untouched.
10 symlinks & traversal: symlink in source (to file outside, to dir) not followed/copied and reported; rel paths with `..`/absolute rejected; symlinked dest component refused; source/library overlap refused (both directions); order/photographer/batch ids with `../` rejected.
11 duplicate task submission -> same task id, one set of rows, one copy; concurrent double-execute -> one runner.
12 cancel then retry -> CANCELLED keeps verified files, retry needs fresh approval, resume completes without duplicating.
13 Lightroom mock partial failure -> stage failed counts exact, successes kept, task FAILED, retry processes only failed assets and then COMPLETED.
14 preview count mismatch -> verify reports missing/orphan/failed precisely; status not OK; repeated export creates run-2 dir, never overwrites run-1.
15 AI repeats the same tool call (plan, execute, lightroom_*) via real MCP stdio client -> idempotent, no duplicate copy/registration/preview.
16 unauthorized: AI execute without approval denied; AI cannot approve (no tool + core PermissionDenied); read-only scope AI cannot plan; execute with stale plan_digest denied; unapproved plan never copies a byte (library empty).
Additional required tests: shared-state proof (CLI plans -> MCP get_task sees it; MCP plans -> CLI `task show --json` equal; CLI approve then MCP execute works; audit shows both actors), MCP tool list contains no path/delete/shell-style tool and no `approve`, state machine illegal transitions, real_mcp adapter allowlist refuses forbidden tools & works against fake server, fault-injection, report content includes MOCK banner when mock.

## E2E
`scripts/e2e_demo.py`: builds mock card (e.g. 12 files: RAW+JPG pairs), temp home, runs: scan -> plan -> approve (human) -> execute (ingest, mock LR register, mock preset, mock export, preview verify) -> report; then reruns execute to show idempotency; writes `evidence/e2e/` (manifest, preview-manifest, report.json/.md, run log, console transcript). Report must say MOCK.

## Status labels used in docs
已完成且测试通过 / 已实现但测试失败 / 仅 Mock 验证 / 待 Mac 实机验证 / 尚未开发.
