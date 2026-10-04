"""Reopening checklist runs: item recording, food-safety submit gates,
cold-hold deadline, review, rework, and the approval cascade."""
from test_helpers import (
    activate_storm,
    ADMIN,
    ApiErrorId,
    assert_checklist_item,
    build_user_headers,
    CHECKLIST_KEYS,
    create_storm,
    create_unit_for,
    deescalate_storm,
    escalate_storm,
    file_condition_report,
    get_storm,
    get_success_data,
    get_unit,
    open_checklist,
    record_all_pass_items,
    record_item,
    set_clock,
    setup_storm_with_unit,
    setup_submittable_checklist,
    setup_submitted_checklist,
    UM,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestChecklistItemShape:
    def test_checklist_item_immutable_no_version_field(self, api, unit_manager_headers):
        """PRD §2.4: "Two resource kinds are deliberately slimmer. `ChecklistItem`
        and `CashDrop` records carry only `id` and `created_at`; both
        `updated_at` and `version` are absent from them, because items are
        replaced rather than updated and cash drops are immutable once recorded."

        Design: Corner/entities/checklist_item_immutable_no_version_field
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        run = open_checklist(uid)
        resp = api.create_checklist_item(
            uid, run["id"], {"key": "POWER_RESTORED", "result": "PASS"},
            unit_manager_headers,
        )
        item = validate_success(resp, 201)
        assert_checklist_item(item)
        assert item["checklist_run_id"] == run["id"]
        assert item["key"] == "POWER_RESTORED"
        assert item["result"] == "PASS"

    def test_fail_checklist_item_requires_note(self, api, unit_manager_headers):
        """PRD §3.5: "Two shape rules apply: items can only be recorded while
        the run is `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), and a `note`
        is mandatory whenever `result` is `FAIL` (otherwise `ERR_VALIDATION`)."

        Design: Corner/validations/fail_checklist_item_requires_note
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        run = open_checklist(uid)
        resp = api.create_checklist_item(
            uid, run["id"], {"key": "GAS_LEAK_CHECK", "result": "FAIL"},
            unit_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        resp = api.create_checklist_item(
            uid, run["id"],
            {"key": "GAS_LEAK_CHECK", "result": "FAIL", "note": "odor at manifold"},
            unit_manager_headers,
        )
        item = validate_success(resp, 201)
        assert item["result"] == "FAIL"

    def test_second_open_checklist_run_rejected(self, api, unit_manager_headers):
        """PRD §3.5: "A `UnitManager` opens a reopening checklist run on the
        unit — but only while no other run of that unit sits in `IN_PROGRESS`
        or `SUBMITTED`; a second open run is rejected with `ERR_INVALID_STATE`."

        Design: Corner/validations/second_open_checklist_run_rejected
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        open_checklist(uid)
        resp = api.create_checklist(uid, None, unit_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        _, meta = validate_paginated(api.list_checklists(uid, unit_manager_headers))
        assert meta["total_count"] == 1


class TestFoodSafetyGates:
    def test_cold_hold_deadline_evaluation_order(self, api, unit_manager_headers):
        """PRD §3.5: "The deadline is exactly four hours after the `reported_at`
        of that latest report. If the latest report is all-clear and the
        logical clock has advanced strictly past that deadline — the comparison
        is strictly greater than, whole-hour precision on the timestamps —
        perishable inventory has exceeded the four-hour cold-hold rule after
        the all-clear; the submission is rejected with `ERR_COLD_HOLD_EXPIRED`,
        and a new all-clear condition report must be filed to restart the
        window."

        Design: Difficulty/combinatorial_formula/cold_hold_deadline_evaluation_order
        """
        ctx = setup_submittable_checklist()
        uid = ctx["unit"]["id"]
        run_id = ctx["run"]["id"]
        set_clock("2026-09-10T14:00:01Z")
        resp = api.submit_checklist(uid, run_id, None, unit_manager_headers)
        validate_error(resp, ApiErrorId.ERR_COLD_HOLD_EXPIRED)
        run = validate_success(api.get_checklist(uid, run_id, unit_manager_headers))
        assert run["status"] == "IN_PROGRESS"
        assert run["submitted_at"] is None

    def test_submit_before_deadline_succeeds_while_late_submit_fails(self, api, unit_manager_headers):
        """PRD §3.5: "The deadline is exactly four hours after the `reported_at`
        of that latest report. If the latest report is all-clear and the
        logical clock has advanced strictly past that deadline — the comparison
        is strictly greater than, whole-hour precision on the timestamps —
        perishable inventory has exceeded the four-hour cold-hold rule after
        the all-clear; the submission is rejected with `ERR_COLD_HOLD_EXPIRED`,
        and a new all-clear condition report must be filed to restart the
        window."

        Design: Difficulty/combinatorial_formula/cold_hold_deadline_evaluation_order
        """
        ctx = setup_submittable_checklist(submit_clock="2026-09-10T13:59:59Z")
        uid = ctx["unit"]["id"]
        run_id = ctx["run"]["id"]
        # One second inside the window the submit succeeds.
        run = validate_success(api.submit_checklist(uid, run_id, None, unit_manager_headers))
        assert run["status"] == "SUBMITTED"
        assert run["submitted_at"] == "2026-09-10T13:59:59.000Z"

    def test_cold_hold_exactly_at_deadline_passes(self, api, unit_manager_headers):
        """PRD §3.5: "The deadline is exactly four hours after the `reported_at`
        of that latest report. If the latest report is all-clear and the
        logical clock has advanced strictly past that deadline — the comparison
        is strictly greater than, whole-hour precision on the timestamps —
        perishable inventory has exceeded the four-hour cold-hold rule after
        the all-clear; the submission is rejected with `ERR_COLD_HOLD_EXPIRED`,
        and a new all-clear condition report must be filed to restart the
        window."

        Design: Corner/calculations/cold_hold_exactly_at_deadline_passes
        """
        ctx = setup_submittable_checklist(submit_clock="2026-09-10T14:00:00Z")
        uid = ctx["unit"]["id"]
        run_id = ctx["run"]["id"]
        run = validate_success(api.submit_checklist(uid, run_id, None, unit_manager_headers))
        assert run["status"] == "SUBMITTED", (
            "exactly at the deadline is not expired — the comparison is strictly greater"
        )
        assert run["submitted_at"] == "2026-09-10T14:00:00.000Z"

    def test_report_not_all_clear_blocks_submit(self, api, unit_manager_headers):
        """PRD §3.5: "The latest condition report for the unit — latest by
        `reported_at`, ties broken by `created_at` ascending, never by `id` —
        must show all four axes `UP`; otherwise `ERR_REPORT_NOT_ALL_CLEAR`."

        Design: Corner/validations/report_not_all_clear_blocks_submit
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T09:00:00Z")
        storm = activate_storm(ctx["storm"])
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        set_clock("2026-09-10T10:00:00Z")
        # Power/water/gas restored (menu_tier FULL) but the payment axis is
        # still DOWN — the latest report is not all-clear.
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="DOWN"
        )
        run = open_checklist(uid)
        record_all_pass_items(uid, run["id"])
        set_clock("2026-09-10T11:00:00Z")
        resp = api.submit_checklist(uid, run["id"], None, unit_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_ALL_CLEAR)
        unit = validate_success(api.get_unit(uid, unit_manager_headers))
        assert unit["menu_tier"] == "FULL", (
            "the payment axis does not affect menu derivation even though the submit failed"
        )


class TestReworkLoop:
    def test_checklist_rework_loop_replaces_fail_item_and_resubmits(self, api, unit_manager_headers):
        """PRD §3.5: "Rejection moves the run to `REJECTED`, from which the
        manager may send it back to `IN_PROGRESS` for rework — items are then
        replaced and the run resubmits through the same gates."
        PRD §3.5: "Re-recording the same `key` while the run is `IN_PROGRESS`
        replaces the earlier item rather than duplicating it."

        Design: Corner/state_machines/checklist_rework_loop_replaces_fail_item_and_resubmits
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T09:00:00Z")
        storm = activate_storm(ctx["storm"])
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        set_clock("2026-09-10T10:00:00Z")
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        run = open_checklist(uid)
        for key in CHECKLIST_KEYS:
            if key == "GAS_LEAK_CHECK":
                record_item(uid, run["id"], key, "FAIL", note="odor at manifold")
            else:
                record_item(uid, run["id"], key, "PASS")
        set_clock("2026-09-10T11:00:00Z")
        submitter = build_user_headers("um-1", "UnitManager")
        resp = api.submit_checklist(uid, run["id"], None, submitter)
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)
        # The FAIL blocked submission, so the run is still IN_PROGRESS; rework
        # the failed item in place and resubmit.
        record_item(uid, run["id"], "GAS_LEAK_CHECK", "PASS", note="re-tested clear")
        items, items_meta = validate_paginated(
            api.list_checklist_items(uid, run["id"], unit_manager_headers)
        )
        gas_items = [i for i in items if i["key"] == "GAS_LEAK_CHECK"]
        assert len(gas_items) == 1, "re-posting the same key must replace the item"
        assert gas_items[0]["result"] == "PASS"
        run = validate_success(api.submit_checklist(uid, run["id"], None, submitter))
        assert run["status"] == "SUBMITTED"
        # Reviewer rejection sends the run to REJECTED; rework reopens it.
        reviewer = build_user_headers("cc-9", "CommandCenterAdmin")
        run = validate_success(api.reject_checklist(uid, run["id"], None, reviewer))
        assert run["status"] == "REJECTED"
        run = validate_success(api.rework_checklist(uid, run["id"], None, unit_manager_headers))
        assert run["status"] == "IN_PROGRESS"
        run = validate_success(api.submit_checklist(uid, run["id"], None, submitter))
        assert run["status"] == "SUBMITTED"
        run = validate_success(api.approve_checklist(uid, run["id"], None, reviewer))
        assert run["status"] == "APPROVED"
        assert validate_success(api.get_unit(uid, unit_manager_headers))["menu_tier"] == "FULL"


class TestApprovalCascade:
    def test_checklist_approval_cascades_to_menu_and_storm_close(self, api):
        """PRD §3.5: "Approval is the compound gate release: the run moves to
        `APPROVED`, the unit's `menu_tier` is set back to `FULL`, any `ACTIVE`
        menu activation on the unit is ended with `ended_at` stamped, and the
        unit's `version` is incremented by one."
        PRD §3.1: "Finally, `RECOVERY` moves to terminal `CLOSED`, stamped with
        `closed_at`, and only when two gates pass together: every registered
        unit's `menu_tier` must be back to `FULL` (otherwise
        `ERR_UNITS_NOT_RESTORED`), and no unit may hold a checklist run in
        `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` (otherwise
        `ERR_OPEN_CHECKLISTS`)."

        Design: Difficulty/transitive_cascade/checklist_approval_cascades_to_menu_and_storm_close
        """
        # Storm: WATCH -> WARNING -> ACTIVE -> RECOVERY (no checklist open at
        # de-escalation time, so the gate passes).
        storm = create_storm(clock="2026-09-10T09:00:00Z")
        unit = create_unit_for(storm, unit_code="U-505", address="21 Palmetto Ave")
        uid = unit["id"]
        storm = escalate_storm(storm)
        storm = activate_storm(storm)
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        ma = validate_success(
            api.create_menu_activation(uid, {"tier": "TIER1_NO_POWER"}, UM), 201
        )
        set_clock("2026-09-10T10:00:00Z")
        # The all-clear report recomputes FULL, ending the TIER1 activation.
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        storm = deescalate_storm(storm)
        assert storm["status"] == "RECOVERY"
        run = open_checklist(uid)
        record_all_pass_items(uid, run["id"])
        set_clock("2026-09-10T12:00:00Z")
        run = validate_success(
            api.submit_checklist(uid, run["id"], None, build_user_headers("um-1", "UnitManager"))
        )
        assert run["status"] == "SUBMITTED"
        run = validate_success(
            api.approve_checklist(uid, run["id"], None, build_user_headers("cc-9", "CommandCenterAdmin"))
        )
        assert run["status"] == "APPROVED"
        unit = get_unit(uid)
        assert unit["menu_tier"] == "FULL"
        activations, _ = validate_paginated(api.list_menu_activations(uid, UM))
        assert activations[0]["id"] == ma["id"]
        assert activations[0]["status"] == "ENDED"
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, ADMIN
        )
        storm = validate_success(resp)
        assert storm["status"] == "CLOSED"
        assert storm["closed_at"] is not None

    def test_close_blocked_before_approval_and_passes_after(self, api):
        """PRD §3.1: "Finally, `RECOVERY` moves to terminal `CLOSED`, stamped
        with `closed_at`, and only when two gates pass together: every
        registered unit's `menu_tier` must be back to `FULL` (otherwise
        `ERR_UNITS_NOT_RESTORED`), and no unit may hold a checklist run in
        `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` (otherwise
        `ERR_OPEN_CHECKLISTS`)."
        PRD §3.5: "Approval is the compound gate release: the run moves to
        `APPROVED`, the unit's `menu_tier` is set back to `FULL`, any `ACTIVE`
        menu activation on the unit is ended with `ended_at` stamped, and the
        unit's `version` is incremented by one."

        Design: Difficulty/transitive_cascade/checklist_approval_cascades_to_menu_and_storm_close
        """
        storm = create_storm(clock="2026-09-10T09:00:00Z")
        unit = create_unit_for(storm, unit_code="U-505", address="21 Palmetto Ave")
        uid = unit["id"]
        storm = activate_storm(storm)
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        set_clock("2026-09-10T10:00:00Z")
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        storm = deescalate_storm(storm)
        run = open_checklist(uid)
        record_all_pass_items(uid, run["id"])
        set_clock("2026-09-10T12:00:00Z")
        # A run still IN_PROGRESS blocks the close with ERR_OPEN_CHECKLISTS.
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_CHECKLISTS)
        assert get_storm(storm["id"])["status"] == "RECOVERY"
        # Submit and approve; the gate unlocks and the same close now succeeds.
        run = validate_success(
            api.submit_checklist(uid, run["id"], None, build_user_headers("um-1", "UnitManager"))
        )
        run = validate_success(
            api.approve_checklist(uid, run["id"], None, build_user_headers("cc-9", "CommandCenterAdmin"))
        )
        assert run["status"] == "APPROVED"
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, ADMIN
        )
        storm = validate_success(resp)
        assert storm["status"] == "CLOSED"

    def test_close_open_checklists_beats_stale_version(self, api):
        """PRD §2.8: "Across the whole API, request validation proceeds in a
        fixed priority order, and an earlier failure masks every later one:"
        PRD §2.8: "11. Fiscal checks — lodging fund sufficiency, storm close
        and de-escalation gates."
        PRD §2.8: "12. Stale-version (OCC) checks last."

        Design: Difficulty/priority_pair_validation_conflict/close_open_checklists_beats_stale_version
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T09:00:00Z")
        storm = activate_storm(ctx["storm"])
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        set_clock("2026-09-10T10:00:00Z")
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        storm = deescalate_storm(storm)
        assert storm["status"] == "RECOVERY"
        run = open_checklist(uid)
        record_all_pass_items(uid, run["id"])
        run = validate_success(
            api.submit_checklist(uid, run["id"], None, build_user_headers("um-1", "UnitManager"))
        )
        run = validate_success(
            api.reject_checklist(uid, run["id"], None, build_user_headers("cc-9", "CommandCenterAdmin"))
        )
        assert run["status"] == "REJECTED"
        # The close request carries BOTH an open-checklist violation (fiscal
        # gate, earlier) and a stale expected version (OCC, last).
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"] - 1}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_CHECKLISTS)
        assert get_storm(storm["id"])["status"] == "RECOVERY"

    def test_close_open_checklists_also_beats_stale_version_on_in_progress_run(self, api):
        """PRD §2.8: "Across the whole API, request validation proceeds in a
        fixed priority order, and an earlier failure masks every later one:"
        PRD §2.8: "11. Fiscal checks — lodging fund sufficiency, storm close
        and de-escalation gates."
        PRD §2.8: "12. Stale-version (OCC) checks last."

        Design: Difficulty/priority_pair_validation_conflict/close_open_checklists_beats_stale_version
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T09:00:00Z")
        storm = activate_storm(ctx["storm"])
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        set_clock("2026-09-10T10:00:00Z")
        file_condition_report(
            uid, power="UP", water="UP", gas="UP", payment_network="UP"
        )
        storm = deescalate_storm(storm)
        # An IN_PROGRESS run is also an open checklist for the close gate.
        open_checklist(uid)
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"] - 1}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_CHECKLISTS)
        assert get_storm(storm["id"])["status"] == "RECOVERY"
