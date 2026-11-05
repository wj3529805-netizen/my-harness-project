# Large-batch (DCIM/143NZ6_3: 120 NEF, 121 JPG incl. unpaired DSC_0558) evidence notes

- **mock-1: PASS_MOCK_NOT_REAL_LIGHTROOM** — rehearsal only, not real-Lightroom verification.
- **run-1: FAIL** (real Lightroom, test catalog). ingest 241/241 verified; lr_register 120/120 (1851 s); lr_preset 100 ok / 20 failed (2009 s) — the last 20 photos got "Lightroom plugin not connected" (17) or `tools/call` timeout (3); export/preview never ran. Source inventory unchanged. Ingest MB/s (~500) is likely inflated by OS cache after mock-1 and is not a card-speed figure. Fix: per-photo transient retry with idempotency checks (30d27f4); a fresh run-2 follows.

## run-2 (2026-11-05, commit c054281) — PASS
- 120 NEF + 121 JPG, all 12 checks passed; single approve; source unchanged; test catalog only.
- LR retries: 0 events (extended budget not exercised).
- NEF subtype: HE 120 / HE★ 0 (all corroborated by bits/pixel).
- Timing: ingest 241 files 2.7 s (~540 MB/s, likely cache-inflated); register 1842 s (15.4 s/photo); preset 2222 s (18.5 s/photo); export 1349 s (11.2 s/photo); preview verify 9.9 s; total 5733 s (~95.5 min); peak RSS ~98 MB.
