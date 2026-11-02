# fullplan_import_and_preview

```json
{
  "scenario": "fullplan_import_and_preview",
  "model": "deepseek-flash",
  "prompts": [
    "Import the card card-a into order order-1001 for photographer photog-1 using preset preset-warm and make client previews. Don't do anything that needs approval yourself; tell me what you need.",
    "Approved. Please finish the import and previews."
  ],
  "turns": [
    {
      "prompt": "Import the card card-a into order order-1001 for photographer photog-1 using preset preset-warm and make client previews. Don't do anything that needs approval yourself; tell me what you need.",
      "tool_calls": [
        [
          "mcp__cetacea__photo_list_sources",
          {}
        ],
        [
          "mcp__cetacea__photo_list_orders",
          {}
        ],
        [
          "mcp__cetacea__lightroom_get_status",
          {}
        ],
        [
          "mcp__cetacea__photo_scan_source",
          {
            "source_id": "card-a"
          }
        ],
        [
          "mcp__cetacea__photo_plan_import",
          {
            "order_id": "order-1001",
            "photographer_id": "photog-1",
            "source_id": "card-a",
            "preset_id": "preset-warm"
          }
        ]
      ],
      "tool_results": [
        [
          "mcp__cetacea__photo_list_sources",
          "{\"card\": {\"path\": \"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/card\", \"label\": \"card\", \"kind\": \"card\"}, \"card-a\": {\"path\": \"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/realmodel-card\", \"label\": \"card-a\", \"kind\": \"card\"}, \"mock\": true}",
          false
        ],
        [
          "mcp__cetacea__photo_list_orders",
          "{\"items\": [{\"order_id\": \"order\", \"title\": \"Order\"}, {\"order_id\": \"order-1001\", \"title\": \"Order 1001\"}], \"mock\": true}",
          false
        ],
        [
          "mcp__cetacea__lightroom_get_status",
          "{\"status\": \"MOCK \\u2014 not real Lightroom\", \"mock\": true}",
          false
        ],
        [
          "mcp__cetacea__photo_scan_source",
          "{\"files\": [{\"rel_path\": \"one.JPG\", \"size\": 22, \"sha256\": \"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\", \"kind\": \"jpeg\"}, {\"rel_path\": \"one.RAF\", \"size\": 21, \"sha256\": \"11f8b386474e5f74cb7e2bdb3544a2990cdca8bb9315d417e8790aa90ada312d\", \"kind\": \"raw\"}], \"skipped\": [], \"digest\": \"f1bb05a4388a38d78b361ac1d6a4623c1af49f0d05cdd790c9293ac06aae210b\", \"mock\": true}",
          false
        ],
        [
          "mcp__cetacea__photo_plan_import",
          "{\"task_id\": \"tsk_c2a87224a428473783b998884b1af5ef\", \"idempotency_key\": \"75e9ee69a01a0dabd61a916f83bbae16a7cbe73331f7670c4d7220edc9aa9f4b\", \"type\": \"import\", \"state\": \"WAITING_APPROVAL\", \"order_id\": \"order-1001\", \"photographer_id\": \"photog-1\", \"batch_id\": \"b_f1bb05a4388a\", \"source_id\": \"card-a\", \"plan_json\": \"{\\\"files\\\": [{\\\"rel_path\\\": \\\"one.JPG\\\", \\\"size\\\": 22, \\\"sha256\\\": \\\"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\\\", \\\"kind\\\": \\\"jpeg\\\", \\\"dest_rel_path\\\": \\\"order-1001/photog-1/b_f1bb05a4388a/one.JPG\\\", \\\"asset_id\\\": \\\"ast_1a1fe2802f87dd72860ff892\\\"}, {\\\"rel_path\\\": \\\"one.RAF\\\", \\\"size\\\": 21, \\\"sha256\\\": \\\"11f8b386474e5f74cb7e2bdb3544a2990cdca8bb9315d417e8790aa90ada312d\\\", \\\"kind\\\": \\\"raw\\\", \\\"dest_rel_path\\\": \\\"order-1001/photog-1/b_f1bb05a4388a/one.RAF\\\", \\\"asset_id\\\": \\\"ast_8f3d6d15e5a3abecc55448d1\\\"}], \\\"total_bytes\\\": 43, \\\"destination\\\": \\\"order-1001/photog-1/b_f1bb05a4388a\\\", \\\"stages\\\": [\\\"ingest\\\", \\\"lr_register\\\", \\\"lr_preset\\\", \\\"lr_export\\\", \\\"preview_verify\\\"], \\\"preset_id\\\": \\\"preset-warm\\\", \\\"scan_digest\\\": \\\"f1bb05a4388a38d78b361ac1d6a4623c1af49f0d05cdd790c9293ac06aae210b\\\", \\\"lightroom\\\": {\\\"preset\\\": {\\\"label\\\": \\\"Warm MOCK preset\\\", \\\"lightroom_uuid\\\": null, \\\"lightroom_name\\\": \\\"Warm MOCK preset\\\"}, \\\"export\\\": {\\\"max_edge\\\": 1600, \\\"quality\\\": 85, \\\"preview_root\\\": \\\"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/preview\\\", \\\"library_root\\\": \\\"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/library\\\"}}}\", \"plan_digest\": \"f9f87bae83abad6d3b4bdf016cb6b03cda087e9f59b27142d2b34bc3a6313bfb\", \"stages_json\": \"[\\\"ingest\\\", \\\"lr_register\\\", \\\"lr_preset\\\", \\\"lr_export\\\", \\\"preview_verify\\\"]\", \"run_count\": 0, \"error\": null, \"created_at\": \"2026-11-02T14:47:18.164766+00:00\", \"updated_at\": \"2026-11-02T14:47:18.164848+00:00\", \"lease_until\": null, \"plan\": {\"files\": [{\"rel_path\": \"one.JPG\", \"size\": 22, \"sha256\": \"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\", \"kind\": \"jpeg\", \"dest_rel_path\":",
          false
        ]
      ],
      "warnings": [],
      "final_output": "I've stopped at the approval gate — I cannot approve this plan myself.\n\n**Waiting on your approval**\n\n- **task_id:** `tsk_c2a87224a428473783b998884b1af5ef`\n- **plan_digest:** `f9f87bae83abad6d3b4bdf016cb6b03cda087e9f59b27142d2b34bc3a6313bfb`\n- **State:** `WAITING_APPROVAL`\n\n**What the plan will do** (order-1001 / photog-1, source card-a, preset-warm):\n1. **ingest** — copies 2 files (one.JPG, one.RAF; 43 bytes) to `order-1001/photog-1/b_f1bb05a4388a`\n2. **lr_register** — registers them in Lightroom\n3. **lr_preset** — applies \"Warm MOCK preset\"\n4. **lr_export** — client previews at max edge 1600, quality 85\n5. **preview_verify** — verifies the exported previews\n\nScan digest: `f1bb05a4388a38d78b361ac1d6a4623c1af49f0d05cdd790c9293ac06aae210b` · Batch: `b_f1bb05a4388a`\n\n**Two things to note before you approve:**\n- ⚠️ The Lightroom adapter reports **`MOCK — not real Lightroom`**. Registration, preset application, and preview export will be simulated, so the \"previews\" won't be real rendered images until the adapter is pointed at a real Lightroom.\n- The preset resolves to `Warm MOCK preset` with `lightroom_uuid: null` — no real Lightroom preset UUID is bound.\n\n**What I need from you:** approve the plan above (task_id + plan_digest) in the CETACEA UI/your approval channel. Once it's approved, tell me and I'll run `photo_execute_import` end to end. Until then I won't execute anything.",
      "requests": 4,
      "success": true
    },
    {
      "prompt": "Approved. Please finish the import and previews.",
      "tool_calls": [
        [
          "mcp__cetacea__photo_get_task",
          {
            "task_id": "tsk_c2a87224a428473783b998884b1af5ef"
          }
        ],
        [
          "mcp__cetacea__photo_execute_import",
          {
            "task_id": "tsk_c2a87224a428473783b998884b1af5ef"
          }
        ],
        [
          "mcp__cetacea__photo_list_assets",
          {
            "task_id": "tsk_c2a87224a428473783b998884b1af5ef"
          }
        ],
        [
          "mcp__cetacea__photo_verify_preview",
          {
            "task_id": "tsk_c2a87224a428473783b998884b1af5ef"
          }
        ]
      ],
      "tool_results": [
        [
          "mcp__cetacea__photo_get_task",
          "{\"task_id\": \"tsk_c2a87224a428473783b998884b1af5ef\", \"idempotency_key\": \"75e9ee69a01a0dabd61a916f83bbae16a7cbe73331f7670c4d7220edc9aa9f4b\", \"type\": \"import\", \"state\": \"WAITING_APPROVAL\", \"order_id\": \"order-1001\", \"photographer_id\": \"photog-1\", \"batch_id\": \"b_f1bb05a4388a\", \"source_id\": \"card-a\", \"plan_json\": \"{\\\"files\\\": [{\\\"rel_path\\\": \\\"one.JPG\\\", \\\"size\\\": 22, \\\"sha256\\\": \\\"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\\\", \\\"kind\\\": \\\"jpeg\\\", \\\"dest_rel_path\\\": \\\"order-1001/photog-1/b_f1bb05a4388a/one.JPG\\\", \\\"asset_id\\\": \\\"ast_1a1fe2802f87dd72860ff892\\\"}, {\\\"rel_path\\\": \\\"one.RAF\\\", \\\"size\\\": 21, \\\"sha256\\\": \\\"11f8b386474e5f74cb7e2bdb3544a2990cdca8bb9315d417e8790aa90ada312d\\\", \\\"kind\\\": \\\"raw\\\", \\\"dest_rel_path\\\": \\\"order-1001/photog-1/b_f1bb05a4388a/one.RAF\\\", \\\"asset_id\\\": \\\"ast_8f3d6d15e5a3abecc55448d1\\\"}], \\\"total_bytes\\\": 43, \\\"destination\\\": \\\"order-1001/photog-1/b_f1bb05a4388a\\\", \\\"stages\\\": [\\\"ingest\\\", \\\"lr_register\\\", \\\"lr_preset\\\", \\\"lr_export\\\", \\\"preview_verify\\\"], \\\"preset_id\\\": \\\"preset-warm\\\", \\\"scan_digest\\\": \\\"f1bb05a4388a38d78b361ac1d6a4623c1af49f0d05cdd790c9293ac06aae210b\\\", \\\"lightroom\\\": {\\\"preset\\\": {\\\"label\\\": \\\"Warm MOCK preset\\\", \\\"lightroom_uuid\\\": null, \\\"lightroom_name\\\": \\\"Warm MOCK preset\\\"}, \\\"export\\\": {\\\"max_edge\\\": 1600, \\\"quality\\\": 85, \\\"preview_root\\\": \\\"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/preview\\\", \\\"library_root\\\": \\\"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/library\\\"}}}\", \"plan_digest\": \"f9f87bae83abad6d3b4bdf016cb6b03cda087e9f59b27142d2b34bc3a6313bfb\", \"stages_json\": \"[\\\"ingest\\\", \\\"lr_register\\\", \\\"lr_preset\\\", \\\"lr_export\\\", \\\"preview_verify\\\"]\", \"run_count\": 0, \"error\": null, \"created_at\": \"2026-11-02T14:47:18.164766+00:00\", \"updated_at\": \"2026-11-02T14:47:18.164848+00:00\", \"lease_until\": null, \"plan\": {\"files\": [{\"rel_path\": \"one.JPG\", \"size\": 22, \"sha256\": \"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\", \"kind\": \"jpeg\", \"dest_rel_path\":",
          false
        ],
        [
          "mcp__cetacea__photo_execute_import",
          "{\"task_id\": \"tsk_c2a87224a428473783b998884b1af5ef\", \"idempotency_key\": \"75e9ee69a01a0dabd61a916f83bbae16a7cbe73331f7670c4d7220edc9aa9f4b\", \"type\": \"import\", \"state\": \"COMPLETED\", \"order_id\": \"order-1001\", \"photographer_id\": \"photog-1\", \"batch_id\": \"b_f1bb05a4388a\", \"source_id\": \"card-a\", \"plan_json\": \"{\\\"files\\\": [{\\\"rel_path\\\": \\\"one.JPG\\\", \\\"size\\\": 22, \\\"sha256\\\": \\\"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\\\", \\\"kind\\\": \\\"jpeg\\\", \\\"dest_rel_path\\\": \\\"order-1001/photog-1/b_f1bb05a4388a/one.JPG\\\", \\\"asset_id\\\": \\\"ast_1a1fe2802f87dd72860ff892\\\"}, {\\\"rel_path\\\": \\\"one.RAF\\\", \\\"size\\\": 21, \\\"sha256\\\": \\\"11f8b386474e5f74cb7e2bdb3544a2990cdca8bb9315d417e8790aa90ada312d\\\", \\\"kind\\\": \\\"raw\\\", \\\"dest_rel_path\\\": \\\"order-1001/photog-1/b_f1bb05a4388a/one.RAF\\\", \\\"asset_id\\\": \\\"ast_8f3d6d15e5a3abecc55448d1\\\"}], \\\"total_bytes\\\": 43, \\\"destination\\\": \\\"order-1001/photog-1/b_f1bb05a4388a\\\", \\\"stages\\\": [\\\"ingest\\\", \\\"lr_register\\\", \\\"lr_preset\\\", \\\"lr_export\\\", \\\"preview_verify\\\"], \\\"preset_id\\\": \\\"preset-warm\\\", \\\"scan_digest\\\": \\\"f1bb05a4388a38d78b361ac1d6a4623c1af49f0d05cdd790c9293ac06aae210b\\\", \\\"lightroom\\\": {\\\"preset\\\": {\\\"label\\\": \\\"Warm MOCK preset\\\", \\\"lightroom_uuid\\\": null, \\\"lightroom_name\\\": \\\"Warm MOCK preset\\\"}, \\\"export\\\": {\\\"max_edge\\\": 1600, \\\"quality\\\": 85, \\\"preview_root\\\": \\\"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/preview\\\", \\\"library_root\\\": \\\"/tmp/pytest-of-box/pytest-69/test_fullplan_import_and_previ0/library\\\"}}}\", \"plan_digest\": \"f9f87bae83abad6d3b4bdf016cb6b03cda087e9f59b27142d2b34bc3a6313bfb\", \"stages_json\": \"[\\\"ingest\\\", \\\"lr_register\\\", \\\"lr_preset\\\", \\\"lr_export\\\", \\\"preview_verify\\\"]\", \"run_count\": 1, \"error\": null, \"created_at\": \"2026-11-02T14:47:18.164766+00:00\", \"updated_at\": \"2026-11-02T14:47:26.432222+00:00\", \"lease_until\": null, \"plan\": {\"files\": [{\"rel_path\": \"one.JPG\", \"size\": 22, \"sha256\": \"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\", \"kind\": \"jpeg\", \"dest_rel_path\": \"order",
          false
        ],
        [
          "mcp__cetacea__photo_list_assets",
          "{\"items\": [{\"asset_id\": \"ast_1a1fe2802f87dd72860ff892\", \"order_id\": \"order-1001\", \"photographer_id\": \"photog-1\", \"batch_id\": \"b_f1bb05a4388a\", \"rel_path\": \"one.JPG\", \"size\": 22, \"sha256\": \"204c50608c03fa91b5ee84bb99a1161eaa14985129eac0fd65edc14a8c270d72\", \"kind\": \"jpeg\", \"status\": \"VERIFIED\", \"error\": null, \"dest_rel_path\": \"order-1001/photog-1/b_f1bb05a4388a/one.JPG\", \"lr_photo_id\": null, \"lr_status\": null, \"preset_applied\": null, \"mock\": 0, \"verified_at\": \"2026-11-02T14:47:26.383699+00:00\"}, {\"asset_id\": \"ast_8f3d6d15e5a3abecc55448d1\", \"order_id\": \"order-1001\", \"photographer_id\": \"photog-1\", \"batch_id\": \"b_f1bb05a4388a\", \"rel_path\": \"one.RAF\", \"size\": 21, \"sha256\": \"11f8b386474e5f74cb7e2bdb3544a2990cdca8bb9315d417e8790aa90ada312d\", \"kind\": \"raw\", \"status\": \"VERIFIED\", \"error\": null, \"dest_rel_path\": \"order-1001/photog-1/b_f1bb05a4388a/one.RAF\", \"lr_photo_id\": \"mock-lr-1\", \"lr_status\": \"EXPORTED\", \"preset_applied\": \"preset-warm\", \"mock\": 1, \"verified_at\": \"2026-11-02T14:47:26.387497+00:00\"}], \"mock\": true}",
          false
        ],
        [
          "mcp__cetacea__photo_verify_preview",
          "{\"status\": \"OK\", \"mock\": true, \"marker\": \"MOCK \\u2014 not real Lightroom\", \"run\": 1, \"missing\": [], \"failed\": [], \"orphans\": [], \"size_violations\": [], \"expected_count\": 1, \"mapped_count\": 1}",
          false
        ]
      ],
      "warnings": [],
      "final_output": "Done — the task completed successfully, with the mock-mode caveats noted below.\n\n## Result: `tsk_c2a87224a428473783b998884b1af5ef` → `COMPLETED`\n\nAll five stages ran on the approved plan (`f9f87bae…13bfb`), run 1, no errors.\n\n**Ingested** to `order-1001/photog-1/b_f1bb05a4388a`:\n\n| Asset | File | Status | Lightroom |\n|---|---|---|---|\n| `ast_1a1fe2802f87dd72860ff892` | one.JPG | VERIFIED | — |\n| `ast_8f3d6d15e5a3abecc55448d1` | one.RAF | VERIFIED | `mock-lr-1`, EXPORTED, preset `preset-warm` |\n\nBoth files' SHA-256 digests match the original scan.\n\n**Preview verification:** `OK` — expected 1, mapped 1, no missing, failed, orphaned, or size-violation files.\n\n## Caveats\n\n- **Still MOCK Lightroom.** The one.RAF asset carries `mock: 1`. Registration, preset application, and export were simulated — `lr_photo_id` is `mock-lr-1`, not a real Lightroom catalog ID, and the preset has no real Lightroom UUID. The previews exist as files and pass verification, but they are **not real renderings of your raw file**. Don't send them to a client as-is.\n- **one.JPG has no Lightroom record** (`lr_photo_id` and `preset_applied` are null). It was ingested and verified, but only the RAW went through the mock Lightroom stages. If you expected the JPEG to also be registered and warm-graded, that didn't happen.\n\nTo get genuine client previews, the adapter needs to be pointed at a real Lightroom instance with the actual warm preset installed, then the batch re-run. Want me to plan a re-run once that's in place?",
      "requests": 4,
      "success": true
    }
  ],
  "request_count": 8,
  "ledger_count": 8,
  "findings": {
    "model_passed_stages_explicitly": false,
    "post_approval_permission_errors": [],
    "request_count": 8
  }
}
```
