"""Seasonal and deferred testing: half-open windows, execution and the sweep."""

from test_helpers import (
    ApiErrorId,
    assert_deferred_test,
    create_deferred_test,
    create_deferred_test_payload,
    get_deferred_test,
    get_issue,
    get_project,
    list_issues,
    register_equipment,
    set_install_status,
    set_logical_clock,
    setup_deferred_issue_with_seasonal_test,
    setup_project_with_approved_plan,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import CXA


def _project_with_installed_unit(name, building, tag, **equipment_overrides):
    base = setup_project_with_approved_plan(
        project_overrides={"name": name, "building_name": building},
        requirement_overrides={"metric_key": "HEATING_CAPACITY_MBH"},
    )
    equipment = register_equipment(
        base["project"]["id"], tag=tag, system_type="BOILER", **equipment_overrides
    )
    set_install_status(equipment["id"], "INSTALLED")
    base["equipment"] = equipment
    return base


class TestSeasonalWindowGeometry:
    def test_a_window_starting_where_an_occupant_ends_is_accepted(self, api):
        """PRD §2.10: "The **seasonal calendar** for deferred testing uses **half-open**
        intervals running from `window_start` inclusive to `window_end` exclusive, with no
        buffer at all."
        PRD §2.10: "Touching endpoints therefore do **not** collide: a new window starting
        exactly when an occupant's window ends is accepted."

        Design: Difficulty/resource_temporal_overlap/seasonal_window_half_open_admits_adjacent_and_blocks_overlap
        """
        base = _project_with_installed_unit("Sable Cx", "Sable Center", "BLR-2")
        first = create_deferred_test(
            base["equipment"]["id"],
            base["requirement"]["id"],
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            season="HEATING",
        )

        adjacent = validate_success(
            api.create_deferred_test(
                create_deferred_test_payload(
                    base["equipment"]["id"],
                    base["requirement"]["id"],
                    "2026-12-01T00:00:00Z",
                    "2027-01-01T00:00:00Z",
                    season="HEATING",
                ),
                CXA,
            ),
            201,
        )
        assert_deferred_test(adjacent)
        assert adjacent["status"] == "PLANNED"
        assert get_deferred_test(first["id"])["status"] == "PLANNED"

    def test_a_genuinely_straddling_window_is_refused(self, api):
        """PRD §3.6: "The seasonal calendar is scoped per equipment unit and admits exactly
        one live window at a time. The occupants are the deferred tests of the **same**
        `equipment_id` whose `status` is `PLANNED` or `BLOCKED`; rows in `EXECUTED_PASS`,
        `EXECUTED_FAIL` or `MISSED` have released their windows."
        PRD §3.6: "Windows here are half-open and unbuffered, so a new window whose
        `window_start` falls exactly on an occupant's `window_end` is accepted, whereas any
        genuine overlap is refused with `ERR_SEASONAL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/seasonal_window_half_open_admits_adjacent_and_blocks_overlap
        """
        base = _project_with_installed_unit("Sable Cx", "Sable Center", "BLR-2")
        create_deferred_test(
            base["equipment"]["id"],
            base["requirement"]["id"],
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            season="HEATING",
        )
        create_deferred_test(
            base["equipment"]["id"],
            base["requirement"]["id"],
            "2026-12-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
            season="HEATING",
        )

        response = api.create_deferred_test(
            create_deferred_test_payload(
                base["equipment"]["id"],
                base["requirement"]["id"],
                "2026-11-30T00:00:00Z",
                "2026-12-15T00:00:00Z",
                season="SHOULDER",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_SEASONAL_WINDOW_CONFLICT.value, 409)

        _, meta = validate_paginated(
            api.list_deferred_tests(
                CXA, params={"equipment_id": base["equipment"]["id"]}
            )
        )
        assert meta["total_count"] == 2, "the refused overlap wrote no row"

    def test_malformed_window_is_reported_before_the_overlap_check(self, api):
        """PRD §2.5: "`scheduled_end` is strictly after `scheduled_start`, and `window_end`
        is strictly after `window_start` — otherwise `ERR_INVALID_WINDOW` (422). Three
        operations are guarded: functional test scheduling, re-test scheduling and deferred
        test scheduling."
        PRD §2.5: "The seasonal-window occupancy check finds no colliding occupant on the
        same equipment unit — otherwise `ERR_SEASONAL_WINDOW_CONFLICT` (409). Only deferred
        test scheduling is guarded."

        Design: Corner/validations/invalid_window_outranks_seasonal_overlap_on_deferred_test_create
        """
        base = _project_with_installed_unit("Window Cx", "Window Block", "BLR-WD")
        create_deferred_test(
            base["equipment"]["id"],
            base["requirement"]["id"],
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            season="HEATING",
        )

        response = api.create_deferred_test(
            create_deferred_test_payload(
                base["equipment"]["id"],
                base["requirement"]["id"],
                "2026-11-15T00:00:00Z",
                "2026-11-10T00:00:00Z",
                season="SHOULDER",
            ),
            CXA,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_SEASONAL_WINDOW_CONFLICT.value
        )

        _, meta = validate_paginated(
            api.list_deferred_tests(
                CXA, params={"equipment_id": base["equipment"]["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestSeasonalExecution:
    def test_execution_outside_the_window_is_refused(self, api):
        """PRD §3.6: "The row must be `PLANNED`, and the logical clock must be at or after
        `window_start` and strictly before `window_end` — outside that half-open span the
        request is refused with `ERR_OUTSIDE_SEASONAL_WINDOW`, which also means a `BLOCKED`
        row cannot be executed at all."

        Design: Corner/state_machines/executing_a_deferred_test_before_its_window_returns_outside_window
        """
        base = _project_with_installed_unit("Early Cx", "Early Block", "BLR-EA")
        deferred = create_deferred_test(
            base["equipment"]["id"],
            base["requirement"]["id"],
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            season="HEATING",
        )

        response = api.execute_deferred_test(
            deferred["id"], {"measured_value": 10_000}, CXA
        )
        validate_error(response, ApiErrorId.ERR_OUTSIDE_SEASONAL_WINDOW.value, 409)

        after = get_deferred_test(deferred["id"])
        assert after["status"] == "PLANNED"
        assert after["executed_at"] is None

    def test_a_passing_execution_inside_the_window_closes_the_linked_deficiency(self, api):
        """PRD §3.6: "The outcome is derived from the linked owner requirement's tolerance
        the same way a functional test's is: a measured value inside the tolerance band
        gives `PLANNED` → `EXECUTED_PASS`, and one outside it gives `PLANNED` →
        `EXECUTED_FAIL`."
        PRD §3.6: "When the row carries an `issue_id` whose issue is sitting in `DEFERRED`,
        the two outcomes diverge: a pass moves that issue `DEFERRED` → `VERIFIED_CLOSED` and
        releases its retainage hold, dropping the engagement's `retainage_withheld_cents` by
        exactly the frozen `retainage_hold_cents`, and because a `DEFERRED` row was never
        counted in `blocking_issue_count`, no demotion or promotion follows from that hop; a
        failure instead returns the issue `DEFERRED` → `OPEN` with `reopen_count`
        incremented by one, putting it back into the severity-index input set."

        Design: Corner/state_machines/executing_a_deferred_test_in_window_closes_the_linked_issue
        """
        setup = setup_deferred_issue_with_seasonal_test()
        set_logical_clock("2026-08-06T00:00:00Z")

        executed = validate_success(
            api.execute_deferred_test(
                setup["deferred_test"]["id"], {"measured_value": 10_000}, CXA
            ),
            200,
        )
        assert executed["status"] == "EXECUTED_PASS"
        assert executed["measured_value"] == 10_000
        assert executed["executed_at"] == "2026-08-06T00:00:00.000Z"

        assert get_issue(setup["issue"]["id"])["status"] == "VERIFIED_CLOSED"

        project = get_project(setup["project"]["id"])
        assert project["retainage_withheld_cents"] == 0
        assert project["issue_severity_index"] == 0.00
        assert project["readiness_posture"] == "OPEN"


class TestSeasonalSweep:
    def test_the_sweep_misses_expired_windows_and_opens_one_issue_each(self, api):
        """PRD §3.6: "The sweep takes every deferred test of the engagement whose `status`
        is `PLANNED` or `BLOCKED` and whose `window_end` is at or before the current logical
        clock, and moves each to `MISSED`."
        PRD §3.6: "For **each** swept row the server opens an issue with `origin`
        `SEASONAL`, `severity` `S2`, the deferred test's equipment as `equipment_id`,
        `source_ref_id` pointing at the deferred test and `opened_by_user_id` of `SYSTEM`;
        and where the swept row carried an `issue_id` whose issue was `DEFERRED`, that issue
        returns to `OPEN` with `reopen_count` incremented by one."

        Design: Corner/state_machines/seasonal_sweep_marks_expired_window_missed_and_opens_issue
        """
        base = setup_project_with_approved_plan(
            project_overrides={"name": "Sweep Cx", "building_name": "Sweep Block"},
            requirement_overrides={"metric_key": "COOLING_CAPACITY_TONS"},
        )
        equipment = register_equipment(
            base["project"]["id"], tag="CHW-SW", system_type="CHILLER"
        )
        set_install_status(equipment["id"], "INSTALLED")
        deferred = create_deferred_test(
            equipment["id"],
            base["requirement"]["id"],
            "2026-08-05T00:00:00Z",
            "2026-08-10T00:00:00Z",
            season="COOLING",
        )
        set_logical_clock("2026-08-20T00:00:00Z")

        validate_success(api.run_seasonal_sweep(base["project"]["id"], CXA), 200)

        assert get_deferred_test(deferred["id"])["status"] == "MISSED"

        rows, meta = list_issues(
            project_id=base["project"]["id"], origin="SEASONAL"
        )
        assert meta["total_count"] == 1
        swept_issue = rows[0]
        assert swept_issue["severity"] == "S2"
        assert swept_issue["status"] == "OPEN"
        assert swept_issue["source_ref_id"] == deferred["id"]
        assert swept_issue["opened_by_user_id"] == "SYSTEM"
        assert swept_issue["retainage_hold_cents"] == 20_000

        project = get_project(base["project"]["id"])
        assert project["issue_severity_index"] == 24.00
        assert project["readiness_posture"] == "RESTRICTED"
        assert project["retainage_withheld_cents"] == 20_000
