# R4 PASS

scope: test-folder-only
source_subdir: DCIM/143NZ6_3
out_of_scope_content_not_listed: true
The card contains other content deliberately not listed, hashed or recorded.
Scenario: target-unplug. Destination-volume unplug means target gone, not source-card unplug; host AC power-off was not tested.
throttled: true
throttle_mbps: 3.0
Source reads were deliberately slowed by this test script (test-induced throttle); throughput figures from this run say nothing about product speed.
hold_mid_file: true
hold_engaged: true
hold_released_by: "target-removed"
hold_result: "HELD_AND_REMOVED"
part_size_at_hold_start: 1048576
part_size_at_removal: 1048576
hold_timeout: 600.0
hold_note: "Mid-file pause was deliberately induced by this test script (test-induced hold); the read or device error after removal is the genuine one."
child_terminated_by_parent: false
part_in_progress_at_interruption: true
parts_after_failure: []
first_failed_file: "DSC_0438.NEF"
first_failed_error_class: "EIO"
failed_file_count: 1
held_file_rel: "DSC_0438.NEF"
held_file_failed_first: true
child_exit_code: 1
later_files_failed_because_card_absent: null
simulated_by_test: false
