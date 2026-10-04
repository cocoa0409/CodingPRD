"""Resource temporal overlap: half-open sanitation windows versus closed
labor windows — opposite touching-endpoint semantics."""

from test_helpers import (
    ApiErrorId,
    OPS_ADMIN_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    validate_error,
    validate_success,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_sanitation_cycle_payload,
    create_labor_assignment_payload,
)


class TestSanitationWindowsTouchingAllowed:
    """Sanitation cycles on a line use half-open windows: touching is allowed,
    strictly-overlapping is rejected."""

    def test_touching_cycle_accepted_overlapping_rejected(self, api):
        """PRD §3.7: "the new cycle must not overlap any non-terminal cycle on
        the same line — touching endpoints are allowed. An overlapping schedule
        is rejected with `ERR_SANITATION_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/sanitation_windows_touching_allowed
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        first = get_success_data(api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z"),
            SHIFT_MANAGER_HEADERS))
        assert first["status"] == "SCHEDULED"

        # Touching: start equals the existing cycle's end.
        touching = validate_success(api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T02:00:00Z", "2026-09-01T03:00:00Z"),
            SHIFT_MANAGER_HEADERS), 201)
        assert touching["status"] == "SCHEDULED"

        # Overlapping: starts one minute before the first cycle ends.
        overlapping = api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T01:59:00Z", "2026-09-01T02:30:00Z"),
            SHIFT_MANAGER_HEADERS)
        validate_error(overlapping, ApiErrorId.ERR_SANITATION_OVERLAP)

    def test_cycle_reversed_window_rejected(self, api):
        """PRD §3.7: "the end must be strictly after the start"
        PRD §2.9: "7. Sanitation temporal rules (`ERR_SANITATION_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/sanitation_windows_touching_allowed
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        response = api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T02:00:00Z", "2026-09-01T01:00:00Z"),
            SHIFT_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.ERR_SANITATION_OVERLAP)


class TestLaborWindowsClosedInterval:
    """Labor assignments use closed intervals: touching endpoints conflict."""

    def test_touching_windows_conflict_one_second_later_accepted(self, api):
        """PRD §3.8: "The window is a closed interval: `window_end` is inclusive,
        must be strictly after `window_start`, and any overlap with an existing
        assignment for the same `staff_user_id` — including merely touching
        endpoints — conflicts and is rejected with `ERR_LABOR_OVERLAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/labor_windows_touching_conflict_closed_interval
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        first = get_success_data(api.create_labor_assignment(
            create_labor_assignment_payload(
                rest["id"], "s1",
                "2026-09-01T09:00:00Z", "2026-09-01T12:00:00Z", to_role="PREP"),
            SHIFT_MANAGER_HEADERS))
        assert first["staff_user_id"] == "s1"

        # Touching: new start equals the existing window's inclusive end.
        touching = api.create_labor_assignment(
            create_labor_assignment_payload(
                rest["id"], "s1",
                "2026-09-01T12:00:00Z", "2026-09-01T15:00:00Z", to_role="HOSPITALITY"),
            SHIFT_MANAGER_HEADERS)
        validate_error(touching, ApiErrorId.ERR_LABOR_OVERLAP)

        # One second later: no shared instant under closed-interval semantics.
        accepted = validate_success(api.create_labor_assignment(
            create_labor_assignment_payload(
                rest["id"], "s1",
                "2026-09-01T12:00:01Z", "2026-09-01T15:00:00Z", to_role="HOSPITALITY"),
            SHIFT_MANAGER_HEADERS), 201)
        assert accepted["staff_user_id"] == "s1"

    def test_distinct_staff_windows_do_not_conflict(self, api):
        """PRD §3.8: "any overlap with an existing assignment for the same
        `staff_user_id` — including merely touching endpoints — conflicts"

        Design: Difficulty/resource_temporal_overlap/labor_windows_touching_conflict_closed_interval
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        get_success_data(api.create_labor_assignment(
            create_labor_assignment_payload(
                rest["id"], "s1",
                "2026-09-01T09:00:00Z", "2026-09-01T12:00:00Z", to_role="PREP"),
            SHIFT_MANAGER_HEADERS))
        # Same window but a different staff member: no conflict.
        other = validate_success(api.create_labor_assignment(
            create_labor_assignment_payload(
                rest["id"], "s2",
                "2026-09-01T09:00:00Z", "2026-09-01T12:00:00Z", to_role="PREP"),
            SHIFT_MANAGER_HEADERS), 201)
        assert other["staff_user_id"] == "s2"
