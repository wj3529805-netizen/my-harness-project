# Other-card / USB reader — 2026-11-06

## run-other-card-20261106-005829 — PASS

Bounded R3 ingest on a **second physical card** via **USB reader** (not the built-in SD slot used in earlier R3).

- Source volume UUID sha256 prefix: `58190fd4ccbea1ac` (USB card). Built-in SD prefix would be `e8a48e01f632f7d9` — runner resolved by UUID only while both were mounted under the same volume name with a macOS `  1` disambiguator on the USB mount.
- `result.json`: `source_protocol=USB`, `source_fs=exfat`, `max_files=12`
- Target: Cetacea Studio (test dir `Cetacea-R3-Test-20261106-005837` only; no production Lightroom catalog / NAS)
- `--source-subdir DCIM/142NZ6_3` (owner: 142/143 are test photos)
- Planned/ingested: **12 NEF / 216,291,840 bytes**; inventory+subtype still cover whole folder (285 NEF: HE★ 247, HE 38)
- Coverage: HE COVERED, HE_STAR COVERED (folder-level subtype)
- Readback: 12/12 VERIFIED; source-compare identical; 1 CLI approval; card stayed read-only
- Timing `mb_per_s≈571` is **not** usable cold-read throughput evidence (inventory had just hashed the same files; OS cache hot). Path proof only.
- No target-unplug; Studio was not pulled. No false write-outside-roots / guard EIO.
- Code prep commit: `72094f3` (`--max-files` + protocol metadata)

Remaining after this item: LICENSE selection still open (other-card/reader closed).
