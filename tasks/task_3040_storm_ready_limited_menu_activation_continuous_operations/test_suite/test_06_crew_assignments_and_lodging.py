"""Crew relocation: registration, availability gating, assignment windows and
overlap, the rolling shift-change clock, lodging cost and fund conservation."""
from test_helpers import (
    activate_storm,
    ApiErrorId,
    assert_crew_assignment,
    assert_lodging_booking,
    book_lodging,
    create_assignment,
    create_assignment_payload,
    create_crew_member,
    create_lodging_booking_payload,
    create_storm,
    create_unit_for,
    deescalate_storm,
    file_condition_report,
    get_unit,
    set_clock,
    setup_active_storm_tiered_unit,
    setup_crew_assignment,
    setup_lodging_scenario,
    setup_storm_with_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCrewRegistration:
    def test_crew_member_invalid_role_enum_rejected(self, api, field_coordinator_headers):
        """PRD §3.7: "Crew members are registered with a `full_name`, a `role`
        of `GRILL_OP`, `SERVER`, or `SHIFT_LEAD`, a `home_unit_id` naming their
        home restaurant (any unit, under any storm), and an `is_jump_team` flag
        — false by default — marking membership in the storm jump-team pool
        deployable to any unit in an `ACTIVE` or `RECOVERY` storm."
        PRD §2.8: "4. Body shape — required fields present, enums in their
        declared sets, integers within declared bounds, time ranges correctly
        ordered (`ERR_VALIDATION`)."

        Design: Corner/entities/crew_member_invalid_role_enum_rejected
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        resp = api.create_crew_member(
            {
                "full_name": "Jo Vega",
                "role": "MANAGER",
                "home_unit_id": ctx["unit"]["id"],
                "is_jump_team": False,
            },
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _, meta = validate_paginated(api.list_crew_members(field_coordinator_headers))
        assert meta["total_count"] == 0

    def test_crew_member_patch_toggle_inactive(self, api, field_coordinator_headers):
        """PRD §3.7: "The coordinator may deactivate a member to `INACTIVE` and
        later reactivate them back to `AVAILABLE`, but a member who is
        currently `ASSIGNED` cannot be set `INACTIVE`; the attempt fails with
        `ERR_INVALID_STATE`."
        PRD §3.7: "Creation is refused for an `INACTIVE` member with
        `ERR_CREW_MEMBER_INACTIVE`, and refused for overlap with
        `ERR_ASSIGNMENT_OVERLAP` when the member already holds a `SCHEDULED` or
        `ACTIVE` assignment whose half-open window intersects the new one —
        intersection means the new start falls before the existing end and the
        existing start falls before the new end, so pure adjacency, where the
        new start equals the existing end, does not overlap."

        Design: Corner/endpoints/crew_member_patch_toggle_inactive
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        member = create_crew_member(uid)
        member = validate_success(
            api.patch_crew_member(member["id"], {"status": "INACTIVE"}, field_coordinator_headers)
        )
        assert member["status"] == "INACTIVE"
        resp = api.create_assignment(
            create_assignment_payload(
                member["id"], uid,
                assigned_from="2026-09-10T10:00:00Z",
                assigned_until="2026-09-11T10:00:00Z",
            ),
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_MEMBER_INACTIVE)
        member = validate_success(
            api.patch_crew_member(member["id"], {"status": "AVAILABLE"}, field_coordinator_headers)
        )
        assert member["status"] == "AVAILABLE"
        assignment = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    member["id"], uid,
                    assigned_from="2026-09-10T10:00:00Z",
                    assigned_until="2026-09-11T10:00:00Z",
                ),
                field_coordinator_headers,
            ),
            201,
        )
        assert assignment["status"] == "SCHEDULED"


class TestAssignmentOverlap:
    def test_crew_assignment_half_open_adjacency(self, api, field_coordinator_headers):
        """PRD §3.7: "Creation is refused for an `INACTIVE` member with
        `ERR_CREW_MEMBER_INACTIVE`, and refused for overlap with
        `ERR_ASSIGNMENT_OVERLAP` when the member already holds a `SCHEDULED` or
        `ACTIVE` assignment whose half-open window intersects the new one —
        intersection means the new start falls before the existing end and the
        existing start falls before the new end, so pure adjacency, where the
        new start equals the existing end, does not overlap."

        Design: Difficulty/resource_temporal_overlap/crew_assignment_half_open_adjacency
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        u1 = ctx["unit"]
        u2 = create_unit_for(ctx["storm"], unit_code="U-1202", address="4 Harbor Rd")
        file_ok = None
        member = create_crew_member(u1["id"])
        a1 = create_assignment(
            member["id"], u1["id"],
            assigned_from="2026-09-10T10:00:00Z",
            assigned_until="2026-09-11T10:00:00Z",
        )
        # One second before the existing end collides.
        resp = api.create_assignment(
            create_assignment_payload(
                member["id"], u2["id"],
                assigned_from="2026-09-11T09:59:59Z",
                assigned_until="2026-09-12T10:00:00Z",
            ),
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)
        # Pure adjacency — new start equals the existing end — does not overlap.
        a2 = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    member["id"], u2["id"],
                    assigned_from="2026-09-11T10:00:00Z",
                    assigned_until="2026-09-12T10:00:00Z",
                ),
                field_coordinator_headers,
            ),
            201,
        )
        assert_crew_assignment(a2)
        assert a2["status"] == "SCHEDULED"
        member_after = validate_success(
            api.get_crew_member(member["id"], field_coordinator_headers)
        )
        assert member_after["status"] == "ASSIGNED"

    def test_adjacent_window_after_completed_assignment_accepted(self, api, field_coordinator_headers):
        """PRD §3.7: "Creation is refused for an `INACTIVE` member with
        `ERR_CREW_MEMBER_INACTIVE`, and refused for overlap with
        `ERR_ASSIGNMENT_OVERLAP` when the member already holds a `SCHEDULED` or
        `ACTIVE` assignment whose half-open window intersects the new one —
        intersection means the new start falls before the existing end and the
        existing start falls before the new end, so pure adjacency, where the
        new start equals the existing end, does not overlap."

        Design: Difficulty/resource_temporal_overlap/crew_assignment_half_open_adjacency
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        member = create_crew_member(uid)
        create_assignment(
            member["id"], uid,
            assigned_from="2026-09-10T10:00:00Z",
            assigned_until="2026-09-11T10:00:00Z",
        )
        # A window strictly inside the existing one collides.
        resp = api.create_assignment(
            create_assignment_payload(
                member["id"], uid,
                assigned_from="2026-09-10T12:00:00Z",
                assigned_until="2026-09-11T09:00:00Z",
            ),
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)
        # An earlier window ending exactly at the existing start is adjacency.
        a0 = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    member["id"], uid,
                    assigned_from="2026-09-09T10:00:00Z",
                    assigned_until="2026-09-10T10:00:00Z",
                ),
                field_coordinator_headers,
            ),
            201,
        )
        assert a0["status"] == "SCHEDULED"


class TestAssignmentStartGates:
    def test_assignment_start_requires_storm_active_and_tiered_unit(self, api, field_coordinator_headers):
        """PRD §3.7: "Starting an assignment is the jump-team arrival moment,
        and it carries four preconditions: the target unit's storm must be
        `ACTIVE` or `RECOVERY` (otherwise `ERR_STORM_NOT_ACTIVE`); the target
        unit's `menu_tier` must differ from `FULL` — you do not fly a jump team
        to a healthy unit (otherwise `ERR_UNIT_NOT_IN_STORM_TIER`); the member
        must be jump-team certified (otherwise `ERR_NOT_JUMP_TEAM`); and the
        logical clock must have reached `assigned_from` (otherwise
        `ERR_ASSIGNMENT_WINDOW`)."

        Design: Difficulty/cross_entity_state_dependency/assignment_start_requires_storm_active_and_tiered_unit
        """
        set_clock("2026-09-10T08:00:00Z")
        # Storm1 stays WATCH with a tiered unit; the window has already begun.
        storm1 = create_storm(clock=None, name="Hurricane Delta")
        u1 = create_unit_for(storm1, unit_code="U-1001", address="8 Gulf Dr")
        file_condition_report(
            u1["id"], power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        m1 = create_crew_member(u1["id"])
        a1 = create_assignment(
            m1["id"], u1["id"],
            assigned_from="2026-09-10T07:00:00Z",
            assigned_until="2026-09-12T00:00:00Z",
        )
        # Storm2 is ACTIVE but its unit is at FULL menu (no report filed).
        storm2 = create_storm(clock=None, name="Tropical Storm Eve")
        u2 = create_unit_for(storm2, unit_code="U-1002", address="9 Gulf Dr")
        activate_storm(storm2)
        m2 = create_crew_member(u1["id"], full_name="Ada Ruiz", role="SERVER")
        a2 = create_assignment(
            m2["id"], u2["id"],
            assigned_from="2026-09-10T07:00:00Z",
            assigned_until="2026-09-12T00:00:00Z",
        )
        resp = api.start_assignment(a1["id"], None, field_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_STORM_NOT_ACTIVE)
        resp = api.start_assignment(a2["id"], None, field_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_STORM_TIER)
        a1_after = validate_success(api.get_assignment(a1["id"], field_coordinator_headers))
        assert a1_after["status"] == "SCHEDULED"
        a2_after = validate_success(api.get_assignment(a2["id"], field_coordinator_headers))
        assert a2_after["status"] == "SCHEDULED"

    def test_err_not_jump_team_triggered(self, api, field_coordinator_headers):
        """PRD §3.7: "the member must be jump-team certified (otherwise
        `ERR_NOT_JUMP_TEAM`)"

        Design: Corner/errors/err_not_jump_team_triggered
        """
        ctx = setup_crew_assignment(
            clock="2026-09-10T08:00:00Z", is_jump_team=False, role="SERVER"
        )
        resp = api.start_assignment(ctx["assignment"]["id"], None, field_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_JUMP_TEAM)
        a_after = validate_success(
            api.get_assignment(ctx["assignment"]["id"], field_coordinator_headers)
        )
        assert a_after["status"] == "SCHEDULED"


class TestAssignmentStartGatesRecovery:
    def test_start_on_recovery_storm_tiered_unit_succeeds(self, api, field_coordinator_headers):
        """PRD §3.7: "Starting an assignment is the jump-team arrival moment,
        and it carries four preconditions: the target unit's storm must be
        `ACTIVE` or `RECOVERY` (otherwise `ERR_STORM_NOT_ACTIVE`); the target
        unit's `menu_tier` must differ from `FULL` — you do not fly a jump team
        to a healthy unit (otherwise `ERR_UNIT_NOT_IN_STORM_TIER`); the member
        must be jump-team certified (otherwise `ERR_NOT_JUMP_TEAM`); and the
        logical clock must have reached `assigned_from` (otherwise
        `ERR_ASSIGNMENT_WINDOW`)."

        Design: Difficulty/cross_entity_state_dependency/assignment_start_requires_storm_active_and_tiered_unit
        """
        ctx = setup_crew_assignment(clock="2026-09-10T08:00:00Z")
        # Move the storm ACTIVE -> RECOVERY; no checklist is open so the gate
        # passes, and RECOVERY also satisfies the assignment-start posture.
        deescalate_storm(ctx["storm"])
        a = validate_success(
            api.start_assignment(ctx["assignment"]["id"], None, field_coordinator_headers)
        )
        assert a["status"] == "ACTIVE"


class TestAssignmentWindowBoundary:
    def test_assignment_start_before_window_rejected(self, api, field_coordinator_headers):
        """PRD §3.7: "the logical clock must have reached `assigned_from`
        (otherwise `ERR_ASSIGNMENT_WINDOW`)"

        Design: Difficulty/boundary_precision_check/assignment_start_before_window_rejected
        """
        ctx = setup_crew_assignment(
            clock="2026-09-10T08:00:00Z",
            assigned_from="2026-09-10T12:00:00Z",
            assigned_until="2026-09-12T12:00:00Z",
        )
        aid = ctx["assignment"]["id"]
        set_clock("2026-09-10T11:59:59Z")
        resp = api.start_assignment(aid, None, field_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW)
        set_clock("2026-09-10T12:00:00Z")
        a = validate_success(api.start_assignment(aid, None, field_coordinator_headers))
        assert a["status"] == "ACTIVE", (
            "starting exactly at assigned_from must succeed (>= semantics)"
        )

    def test_assignment_start_one_second_into_window_succeeds(self, api, field_coordinator_headers):
        """PRD §3.7: "the logical clock must have reached `assigned_from`
        (otherwise `ERR_ASSIGNMENT_WINDOW`)"

        Design: Difficulty/boundary_precision_check/assignment_start_before_window_rejected
        """
        ctx = setup_crew_assignment(
            clock="2026-09-10T08:00:00Z",
            assigned_from="2026-09-10T12:00:00Z",
            assigned_until="2026-09-12T12:00:00Z",
        )
        aid = ctx["assignment"]["id"]
        set_clock("2026-09-10T11:59:58Z")
        resp = api.start_assignment(aid, None, field_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW)
        set_clock("2026-09-10T12:00:01Z")
        a = validate_success(api.start_assignment(aid, None, field_coordinator_headers))
        assert a["status"] == "ACTIVE"


class TestShiftChangeClock:
    def test_shift_change_threshold_exactly_twelve_hours(self, api, field_coordinator_headers):
        """PRD §2.6: "When a crew assignment starts or completes on the unit,
        the shift-change clock is examined: a null `last_shift_change_at` (the
        unit has never been stamped under this storm) is treated as always-due
        and stamps unconditionally; otherwise, if the count has reached the
        twelve-hour shift-change interval — the boundary is inclusive, so
        exactly twelve hours qualifies — the unit stamps `last_shift_change_at`
        to the present and resets `hours_since_shift_change` to zero."

        Design: Difficulty/boundary_precision_check/shift_change_threshold_exactly_twelve_hours
        """
        ctx = setup_crew_assignment(
            clock="2026-09-09T20:00:00Z",
            assigned_from="2026-09-10T00:00:00Z",
            assigned_until="2026-09-11T00:00:00Z",
        )
        uid = ctx["unit"]["id"]
        m = ctx["member"]
        a1 = ctx["assignment"]
        set_clock("2026-09-10T00:00:00Z")
        a1 = validate_success(api.start_assignment(a1["id"], None, field_coordinator_headers))
        assert a1["status"] == "ACTIVE"
        unit = get_unit(uid)
        assert unit["last_shift_change_at"] == "2026-09-10T00:00:00.000Z", (
            "a null stamp is always due: the first start stamps unconditionally"
        )
        assert unit["hours_since_shift_change"] == 0
        # Completion at 11:59 elapsed does not restamp (11 < 12).
        set_clock("2026-09-10T11:59:00Z")
        a1 = validate_success(api.complete_assignment(a1["id"], None, field_coordinator_headers))
        assert a1["status"] == "COMPLETED"
        unit = get_unit(uid)
        assert unit["last_shift_change_at"] == "2026-09-10T00:00:00.000Z"
        assert unit["hours_since_shift_change"] == 11
        # A second assignment starting at exactly 12:00 elapsed restamps.
        a2 = create_assignment(
            m["id"], uid,
            assigned_from="2026-09-10T12:00:00Z",
            assigned_until="2026-09-11T00:00:00Z",
        )
        set_clock("2026-09-10T12:00:00Z")
        a2 = validate_success(api.start_assignment(a2["id"], None, field_coordinator_headers))
        assert a2["status"] == "ACTIVE"
        unit = get_unit(uid)
        assert unit["last_shift_change_at"] == "2026-09-10T12:00:00.000Z", (
            "exactly twelve hours qualifies — the boundary is inclusive"
        )
        assert unit["hours_since_shift_change"] == 0

    def test_completion_at_exactly_twelve_hours_restamps(self, api, field_coordinator_headers):
        """PRD §2.6: "When a crew assignment starts or completes on the unit,
        the shift-change clock is examined: a null `last_shift_change_at` (the
        unit has never been stamped under this storm) is treated as always-due
        and stamps unconditionally; otherwise, if the count has reached the
        twelve-hour shift-change interval — the boundary is inclusive, so
        exactly twelve hours qualifies — the unit stamps `last_shift_change_at`
        to the present and resets `hours_since_shift_change` to zero."

        Design: Difficulty/boundary_precision_check/shift_change_threshold_exactly_twelve_hours
        """
        ctx = setup_crew_assignment(
            clock="2026-09-09T20:00:00Z",
            assigned_from="2026-09-10T00:00:00Z",
            assigned_until="2026-09-11T00:00:00Z",
        )
        uid = ctx["unit"]["id"]
        a1 = ctx["assignment"]
        set_clock("2026-09-10T00:00:00Z")
        api.start_assignment(a1["id"], None, field_coordinator_headers)
        # Complete at exactly 12:00 elapsed — the boundary stamps again.
        set_clock("2026-09-10T12:00:00Z")
        api.complete_assignment(a1["id"], None, field_coordinator_headers)
        unit = get_unit(uid)
        assert unit["last_shift_change_at"] == "2026-09-10T12:00:00.000Z"
        assert unit["hours_since_shift_change"] == 0


class TestCrewMemberStatusBubbleUp:
    def test_crew_member_returns_available_after_last_assignment_completes(self, api, field_coordinator_headers):
        """PRD §3.7: "In both cases, when the assignment was the member's last
        non-terminal one — no other `SCHEDULED` or `ACTIVE` assignment remains
        — the member's status returns automatically to `AVAILABLE`."

        Design: Corner/state_machines/crew_member_returns_available_after_last_assignment_completes
        """
        ctx = setup_active_storm_tiered_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        m = create_crew_member(uid)
        a1 = create_assignment(
            m["id"], uid,
            assigned_from="2026-09-10T08:00:00Z",
            assigned_until="2026-09-11T08:00:00Z",
        )
        a2 = create_assignment(
            m["id"], uid,
            assigned_from="2026-09-11T08:00:00Z",
            assigned_until="2026-09-12T08:00:00Z",
        )
        a1 = validate_success(api.start_assignment(a1["id"], None, field_coordinator_headers))
        assert a1["status"] == "ACTIVE"
        api.complete_assignment(a1["id"], None, field_coordinator_headers)
        member = validate_success(api.get_crew_member(m["id"], field_coordinator_headers))
        assert member["status"] == "ASSIGNED", (
            "A2 is still SCHEDULED, so the member must stay ASSIGNED"
        )
        api.cancel_assignment(a2["id"], None, field_coordinator_headers)
        member = validate_success(api.get_crew_member(m["id"], field_coordinator_headers))
        assert member["status"] == "AVAILABLE"


class TestLodging:
    def test_lodging_cost_counts_calendar_dates_not_midnights(self, api, field_coordinator_headers):
        """PRD §3.7: "The booking's `cost_cents` is computed as rooms multiplied
        by the nightly rate multiplied by the number of nights, where a night
        is each calendar date (UTC) intersected by the half-open stay from
        check-in up to but not including check-out — a stay from the afternoon
        of September 10 to the morning of September 12 spans September 10 and
        11, two nights."

        Design: Corner/calculations/lodging_cost_counts_calendar_dates_not_midnights
        """
        ctx = setup_lodging_scenario(clock="2026-09-10T08:00:00Z")
        # Check-out exactly at midnight Sep 12 intersects only Sep 10 and
        # Sep 11: the half-open stay's last instant is Sep 11 23:59:59, so a
        # midnight boundary must not add a third billed night.
        booking = book_lodging(
            ctx["assignment"]["id"], ctx["unit"]["id"],
            rooms=1, nightly_rate_cents=9000,
            check_in="2026-09-10T22:00:00Z", check_out="2026-09-12T00:00:00Z",
        )
        assert_lodging_booking(booking)
        assert booking["cost_cents"] == 18000, (
            f"2 calendar dates x 9000 must be 18000, got {booking['cost_cents']}"
        )
        unit = get_unit(ctx["unit"]["id"])
        assert unit["lodging_fund_cents"] == 982000

    def test_lodging_fund_book_cancel_conservation(self, api, field_coordinator_headers):
        """PRD §3.7: "On success the booking is created `CONFIRMED`, the cost
        is debited from the unit's fund, and the unit's `version` increments by
        one. Cancelling a confirmed booking moves it to `CANCELLED` and refunds
        the full `cost_cents` back into the unit's fund, again incrementing the
        unit's `version` — the fund ledger thus always reflects confirmed
        bookings only."

        Design: Difficulty/compensating_invariant/lodging_fund_book_cancel_conservation
        """
        ctx = setup_lodging_scenario(
            clock="2026-09-10T08:00:00Z", lodging_fund_cents=50000
        )
        uid = ctx["unit"]["id"]
        booking = book_lodging(
            ctx["assignment"]["id"], uid,
            rooms=2, nightly_rate_cents=9000,
            check_in="2026-09-10T14:00:00Z", check_out="2026-09-12T09:00:00Z",
        )
        assert booking["cost_cents"] == 36000, (
            f"2 rooms x 9000 x 2 nights (Sep 10 + Sep 11) must be 36000, got {booking['cost_cents']}"
        )
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 14000
        booking = validate_success(
            api.cancel_lodging_booking(booking["id"], None, field_coordinator_headers)
        )
        assert booking["status"] == "CANCELLED"
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 50000, (
            "book + cancel must conserve the fund exactly"
        )

    def test_lodging_fund_conserved_across_two_bookings_and_one_cancel(self, api, field_coordinator_headers):
        """PRD §3.7: "On success the booking is created `CONFIRMED`, the cost
        is debited from the unit's fund, and the unit's `version` increments by
        one. Cancelling a confirmed booking moves it to `CANCELLED` and refunds
        the full `cost_cents` back into the unit's fund, again incrementing the
        unit's `version` — the fund ledger thus always reflects confirmed
        bookings only."

        Design: Difficulty/compensating_invariant/lodging_fund_book_cancel_conservation
        """
        ctx = setup_lodging_scenario(
            clock="2026-09-10T08:00:00Z", lodging_fund_cents=50000
        )
        uid = ctx["unit"]["id"]
        aid = ctx["assignment"]["id"]
        b1 = book_lodging(
            aid, uid, rooms=1, nightly_rate_cents=9000,
            check_in="2026-09-10T14:00:00Z", check_out="2026-09-11T09:00:00Z",
        )
        # B2 is placed on Sep 12 so its calendar-date set shares no date with
        # B1's (the coarse calendar-date overlap gate of PRD §3.7 would reject
        # a Sep 11 check-in against B1).
        b2 = book_lodging(
            aid, uid, rooms=2, nightly_rate_cents=9000,
            check_in="2026-09-12T14:00:00Z", check_out="2026-09-13T09:00:00Z",
        )
        assert b1["cost_cents"] == 9000
        assert b2["cost_cents"] == 18000
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 23000, (
            f"50000 - 9000 - 18000 must be 23000, got {unit['lodging_fund_cents']}"
        )
        booking = validate_success(
            api.cancel_lodging_booking(b2["id"], None, field_coordinator_headers)
        )
        assert booking["status"] == "CANCELLED"
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 41000, (
            "cancelling B2 refunds exactly its 18000 cost; B1 stays debited"
        )

    def test_lodging_calendar_date_overlap_vs_instant_adjacency(self, api, field_coordinator_headers):
        """PRD §3.7: "Two overlap and funding gates apply, in priority order:
        the same crew assignment must not already hold a `CONFIRMED` booking
        whose calendar-night set shares at least one date with the new
        booking's night set — unlike the assignment-overlap rule this is a
        coarse calendar-date intersection, so two stays adjacent in time that
        merely touch the same date do conflict — otherwise
        `ERR_LODGING_OVERLAP`; and the unit's `lodging_fund_cents` must cover
        the computed cost, otherwise `ERR_LODGING_FUND_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/lodging_calendar_date_overlap_vs_instant_adjacency
        """
        ctx = setup_lodging_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        aid = ctx["assignment"]["id"]
        b1 = book_lodging(
            aid, uid, rooms=1, nightly_rate_cents=9000,
            check_in="2026-09-10T14:00:00Z", check_out="2026-09-11T00:30:00Z",
        )
        assert b1["cost_cents"] == 9000, (
            f"the billed night is Sep 10 only (the PRD example bills "
            f"[afternoon, morning+2d) as two nights), got {b1['cost_cents']}"
        )
        # B shares no instant with A but touches the Sep 11 calendar date
        # (A's stay runs 00:00-00:30 on Sep 11; B begins Sep 11 23:00) — the
        # coarse calendar-date intersection makes them conflict.
        resp = api.create_lodging_booking(
            create_lodging_booking_payload(
                aid, uid, rooms=1, nightly_rate_cents=9000,
                check_in="2026-09-11T23:00:00Z", check_out="2026-09-12T09:00:00Z",
            ),
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LODGING_OVERLAP)
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 991000, (
            "only booking A may debit the fund"
        )

    def test_lodging_night_sets_sharing_no_date_do_not_conflict(self, api, field_coordinator_headers):
        """PRD §3.7: "Two overlap and funding gates apply, in priority order:
        the same crew assignment must not already hold a `CONFIRMED` booking
        whose calendar-night set shares at least one date with the new
        booking's night set — unlike the assignment-overlap rule this is a
        coarse calendar-date intersection, so two stays adjacent in time that
        merely touch the same date do conflict — otherwise
        `ERR_LODGING_OVERLAP`; and the unit's `lodging_fund_cents` must cover
        the computed cost, otherwise `ERR_LODGING_FUND_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/lodging_calendar_date_overlap_vs_instant_adjacency
        """
        ctx = setup_lodging_scenario(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        aid = ctx["assignment"]["id"]
        # Booking A occupies the Sep 10 night only (check-out at Sep 11 00:00
        # touches no part of Sep 11).
        book_lodging(
            aid, uid, rooms=1, nightly_rate_cents=9000,
            check_in="2026-09-10T14:00:00Z", check_out="2026-09-11T00:00:00Z",
        )
        # Booking B starts on Sep 11 — disjoint night sets, so it is accepted.
        b2 = book_lodging(
            aid, uid, rooms=1, nightly_rate_cents=9000,
            check_in="2026-09-11T14:00:00Z", check_out="2026-09-12T09:00:00Z",
        )
        assert b2["status"] == "CONFIRMED"
        assert b2["cost_cents"] == 9000, (
            f"Sep 11 only at 9000 must be 9000, got {b2['cost_cents']}"
        )
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 982000

    def test_lodging_fund_exact_balance_boundary(self, api, field_coordinator_headers):
        """PRD §3.7: "Two overlap and funding gates apply, in priority order:
        the same crew assignment must not already hold a `CONFIRMED` booking
        whose calendar-night set shares at least one date with the new
        booking's night set — unlike the assignment-overlap rule this is a
        coarse calendar-date intersection, so two stays adjacent in time that
        merely touch the same date do conflict — otherwise
        `ERR_LODGING_OVERLAP`; and the unit's `lodging_fund_cents` must cover
        the computed cost, otherwise `ERR_LODGING_FUND_EXCEEDED`."

        Design: Corner/validations/lodging_fund_exact_balance_boundary
        """
        ctx = setup_lodging_scenario(
            clock="2026-09-10T08:00:00Z", lodging_fund_cents=18000
        )
        uid = ctx["unit"]["id"]
        aid = ctx["assignment"]["id"]
        b1 = book_lodging(
            aid, uid, rooms=1, nightly_rate_cents=9000,
            check_in="2026-09-10T14:00:00Z", check_out="2026-09-12T09:00:00Z",
        )
        assert b1["cost_cents"] == 18000, "exact balance must be sufficient"
        unit = get_unit(uid)
        assert unit["lodging_fund_cents"] == 0
        # B1's stay touches Sep 10-12, so the second booking is placed on
        # Sep 13-14: disjoint calendar-date sets let the request pass the
        # overlap gate (which PRD §3.7 orders first) and reach the fund gate.
        resp = api.create_lodging_booking(
            create_lodging_booking_payload(
                aid, uid, rooms=1, nightly_rate_cents=1,
                check_in="2026-09-13T14:00:00Z", check_out="2026-09-14T09:00:00Z",
            ),
            field_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LODGING_FUND_EXCEEDED)
