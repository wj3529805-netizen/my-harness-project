# Large-batch (DCIM/143NZ6_3: 120 NEF, 121 JPG incl. unpaired DSC_0558) evidence notes

- **mock-1: PASS_MOCK_NOT_REAL_LIGHTROOM** — rehearsal only, not real-Lightroom verification.
- **run-1: FAIL** (real Lightroom, test catalog). ingest 241/241 verified; lr_register 120/120 (1851 s); lr_preset 100 ok / 20 failed (2009 s) — the last 20 photos got "Lightroom plugin not connected" (17) or `tools/call` timeout (3); export/preview never ran. Source inventory unchanged. Ingest MB/s (~500) is likely inflated by OS cache after mock-1 and is not a card-speed figure. Fix: per-photo transient retry with idempotency checks (30d27f4); a fresh run-2 follows.
