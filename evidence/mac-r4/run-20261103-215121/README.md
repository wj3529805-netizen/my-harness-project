# R4 PASS

scope: test-folder-only
source_subdir: DCIM/142NZ6_3
out_of_scope_content_not_listed: true
The card contains other content deliberately not listed, hashed or recorded.
Scenario: unplug. Real power-off is out of scope.
throttled: true
throttle_mbps: 3.0
Source reads were deliberately slowed by this test script (test-induced throttle); throughput figures from this run say nothing about product speed.
hold_mid_file: true
hold_engaged: true
hold_released_by: "card-removed"
hold_result: "HELD_AND_REMOVED"
part_size_at_hold_start: 1048576
part_size_at_removal: 1048576
hold_timeout: 600.0
hold_note: "Mid-file pause was deliberately induced by this test script (test-induced hold); the source read error after removal is the genuine one."
child_terminated_by_parent: false
part_in_progress_at_interruption: true
parts_after_failure: []
first_failed_file: "DSC_9717.NEF"
first_failed_error_class: "EIO"
failed_file_count: 8
held_file_rel: "DSC_9717.NEF"
held_file_failed_first: true
child_exit_code: 1
later_files_failed_because_card_absent: "Later files reported card-absence/device errors after removal."
simulated_by_test: false
