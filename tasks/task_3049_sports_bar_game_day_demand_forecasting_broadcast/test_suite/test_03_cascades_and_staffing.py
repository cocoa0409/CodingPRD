"""Transitive cascades (event cancel, order-line void), the staffing
publish/revert cycle, and the check-settlement rounding chain."""

from test_helpers import (
    HOST_HEADERS,
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
    add_order_line,
    add_shift,
    advance_clock,
    create_event,
    create_guest,
    create_open_check,
    create_promo_rule,
    create_publishable_plan,
    create_screen_assignment,
    create_staffing_plan,
    create_venue,
    create_zone,
    get_guest,
    join_waitlist,
    shift_payload,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId


class TestEventCancelCascadeZoneWaitlist:
    """Cancelling an event unwinds the assignment, the zone posture, and the
    waitlist gate in one cascade."""

    def _setup_full_zone(self, api):
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Bills vs Jets",
            expected_attendance=9000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_screen_assignment(zone["id"], event["id"])
        return venue, zone, event

    def test_cancel_drops_the_zone_to_open_and_unblocks_the_waitlist(self, api):
        """PRD §3.2: "cancellation is a `Scheduler` action with wide blast radius — every screen assignment referencing the event is removed, every affected zone recomputes its `primary_event_id` and `posture`, and forecasts recompute excluding the event."

        While the zone's primary event forecasts 9000 attendees against 200
        seats the zone is FULL and joining the waitlist is rejected; after the
        event is cancelled the zone drops to OPEN and the join succeeds.

        Design: Difficulty/transitive_cascade/event_cancel_cascade_zone_waitlist
        """
        venue, zone, event = self._setup_full_zone(api)
        guest = create_guest(venue["id"])

        zone_before = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))
        assert zone_before["posture"] == "FULL"

        validate_success(api.cancel_event(event["id"], SCHEDULER_HEADERS))

        zone_after = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))
        entry = validate_success(
            api.join_waitlist(
                {"venue_id": venue["id"], "guest_id": guest["id"], "party_size": 4},
                HOST_HEADERS,
            ),
            expected_status=201,
        )

        assert zone_after["posture"] == "OPEN"
        assert zone_after["primary_event_id"] is None
        assert entry["status"] == "WAITING"

    def test_cancel_removes_the_screen_assignments_for_the_event(self, api):
        """PRD §3.2: "cancellation is a `Scheduler` action with wide blast radius — every screen assignment referencing the event is removed, every affected zone recomputes its `primary_event_id` and `posture`, and forecasts recompute excluding the event."

        After cancellation the zone's assignment list no longer references
        the cancelled event.

        Design: Difficulty/transitive_cascade/event_cancel_cascade_zone_waitlist
        """
        venue, zone, event = self._setup_full_zone(api)

        validate_success(api.cancel_event(event["id"], SCHEDULER_HEADERS))

        assignments = validate_success(
            api.list_zone_screen_assignments(zone["id"], VENUE_MANAGER_HEADERS)
        )
        assert all(a["event_id"] != event["id"] for a in assignments)


class TestOrderLineVoidCascadeCheckTotal:
    """Voiding a line recomputes the check subtotal, which flows through tax
    and total at settle."""

    def test_subtotal_drops_the_voided_line_and_settle_uses_the_new_subtotal(self, api):
        """PRD §3.5: "Voiding a line — possible only while the check identified by the line's `check_id` is still `OPEN`, else `ERR_INVALID_STATE` — moves the line from `OPEN` to `VOID` and recomputes the check's `subtotal_cents` excluding it."
        PRD §3.5: "On settle, `tax_cents` is the subtotal times 0.05 rounded half-up."

        Two 20-piece lines at the 150-cent base price give a subtotal of 6000;
        voiding one leaves 3000, and settling charges 150 tax for a 3150 total.

        Design: Difficulty/transitive_cascade/order_line_void_cascade_check_total
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        check = create_open_check(venue["id"], guest["id"])
        line1 = add_order_line(check["id"], portion_count=2)
        add_order_line(check["id"], portion_count=2)

        validate_success(api.void_order_line(line1["id"], SERVER_HEADERS))

        check_after_void = validate_success(api.get_check(check["id"], SERVER_HEADERS))
        check_settled = validate_success(api.settle_check(check["id"], SERVER_HEADERS))

        assert check_after_void["subtotal_cents"] == 3000
        assert check_settled["tax_cents"] == 150
        assert check_settled["total_cents"] == 3150
        assert check_settled["status"] == "SETTLED"

    def test_settled_check_reflects_only_non_void_lines(self, api):
        """PRD §3.5: "The check's `subtotal_cents` is always the sum of `line_total_cents` over its non-void lines."

        With one of two identical lines voided, the settled subtotal is
        exactly the surviving line's total.

        Design: Difficulty/transitive_cascade/order_line_void_cascade_check_total
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        check = create_open_check(venue["id"], guest["id"])
        line1 = add_order_line(check["id"], portion_count=2)
        line2 = add_order_line(check["id"], portion_count=2)

        validate_success(api.void_order_line(line1["id"], SERVER_HEADERS))
        check_settled = validate_success(api.settle_check(check["id"], SERVER_HEADERS))

        assert check_settled["subtotal_cents"] == line2["line_total_cents"]
        assert check_settled["total_cents"] == line2["line_total_cents"] + 150


class TestStaffingPlanPublishRevertCycle:
    """The DRAFT -> PUBLISHED -> DRAFT cycle is guarded by the logical clock."""

    def test_publish_then_revert_while_no_shift_has_started(self, api):
        """PRD §3.7: "Publishing moves the plan from `DRAFT` to `PUBLISHED` and requires at least one shift and that both `foh_required` and `boh_required` are greater than zero."
        PRD §3.7: "A published plan may be reverted to `DRAFT` only while no shift has started yet — every shift's `start_time` must still be in the future — after which staffing formulas recompute on the next shift change."

        With a single shift starting 2026-09-14T16:00Z and the logical clock
        still at its default (2026-09-01), publish then revert both succeed.

        Design: Difficulty/non_linear_state_machine/staffing_plan_publish_revert_cycle
        """
        venue = create_venue()
        plan = create_staffing_plan(venue["id"])
        add_shift(plan["id"], role="FOH", expected_covers=3600)

        plan_pub = validate_success(api.publish_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS))
        plan_rev = validate_success(api.revert_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS))

        assert plan_pub["status"] == "PUBLISHED"
        assert plan_rev["status"] == "DRAFT"

    def test_publish_without_shifts_is_rejected(self, api):
        """PRD §3.7: "Publishing moves the plan from `DRAFT` to `PUBLISHED` and requires at least one shift and that both `foh_required` and `boh_required` are greater than zero."

        A plan with no shifts has no path to positive requirements, so the
        publish attempt is rejected as an invalid state transition.

        Design: Difficulty/non_linear_state_machine/staffing_plan_publish_revert_cycle
        """
        venue = create_venue()
        plan = create_staffing_plan(venue["id"], name="Empty Plan")

        resp = api.publish_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEventCheckTotalRoundingOrder:
    """Per-unit, per-line, then per-check rounding produces cents that a
    sum-first-then-round implementation cannot reproduce."""

    def test_five_promo_lines_round_per_unit_then_per_line_then_tax(self, api):
        """PRD §2.7: "Where a division produces a fractional cent, values are rounded half-up to the nearest cent — but the rounding order is fixed and load-bearing: unit prices are rounded per unit first, line totals are rounded per line second, and check-level tax is rounded last."
        PRD §3.5: "On settle, `tax_cents` is the subtotal times 0.05 rounded half-up."

        With a Sunday promo at 1100 per 10 wings and a guest whose rolling
        30-day consumption exceeds 5000 pieces, each unit is round(110 * 1.10)
        = 121 cents; each 10-piece line is round(121 * 10 * 1.0) = 1210... five
        lines of one portion each give subtotal 5 * 1210 = 6050 with the
        staged rounding, tax round(6050 * 0.05) = 303, total 6353.

        Design: Difficulty/combinatorial_formula/event_check_total_rounding_order_mode_b
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        create_promo_rule(
            day_of_week=6,
            wing_kind="TRADITIONAL",
            promo_price_cents_per_10=1100,
            start_date="2026-09-01T00:00:00Z",
            end_date="2026-09-30T23:59:59Z",
        )
        # Push the guest's rolling settled consumption past 5000 pieces so the
        # 1.10 surcharge engages on every line of the check under test.
        # 2026-09-01 through 2026-09-30 is within 30 days of the clock start
        # plus the promo's Sunday (2026-09-13); each seed line settles 510
        # pieces, so eleven seed checks accumulate 5610 pieces.
        for _ in range(11):
            seed = create_open_check(venue["id"], guest["id"])
            add_order_line(seed["id"], kind="TRADITIONAL", portion_count=51)
            validate_success(api.settle_check(seed["id"], SERVER_HEADERS))

        # Advance the logical clock to Sunday 2026-09-13 so the day_of_week=6
        # promo matches the order lines added below.
        advance_clock("2026-09-13T12:00:00Z")

        check = create_open_check(venue["id"], guest["id"])
        for _ in range(5):
            add_order_line(check["id"], kind="TRADITIONAL", portion_count=1)

        settled = validate_success(api.settle_check(check["id"], SERVER_HEADERS))

        # unit = round_half_up(110 * 1.10) = 121; line = 121 * 10 * 1.0 = 1210;
        # subtotal = 5 * 1210 = 6050; tax = round_half_up(6050 * 0.05) = 303.
        assert settled["subtotal_cents"] == 6050
        assert settled["tax_cents"] == 303
        assert settled["total_cents"] == 6353
        assert settled["status"] == "SETTLED"

    def test_check_without_surcharge_keeps_plain_promo_pricing(self, api):
        """PRD §2.7: "Summing unrounded amounts and rounding once at the end is a different calculation and produces different cents; implementations must follow the staged order."

        With no surcharge in play the same five promo lines price at a flat
        110-cent unit: subtotal 5500, tax 275, total 5775.

        Design: Difficulty/combinatorial_formula/event_check_total_rounding_order_mode_b
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        create_promo_rule(
            day_of_week=6,
            wing_kind="TRADITIONAL",
            promo_price_cents_per_10=1100,
            start_date="2026-09-01T00:00:00Z",
            end_date="2026-09-30T23:59:59Z",
        )

        # Advance the logical clock to Sunday 2026-09-13 so the day_of_week=6
        # promo matches the order lines added below.
        advance_clock("2026-09-13T12:00:00Z")

        check = create_open_check(venue["id"], guest["id"])
        for _ in range(5):
            add_order_line(check["id"], kind="TRADITIONAL", portion_count=1)

        settled = validate_success(api.settle_check(check["id"], SERVER_HEADERS))

        assert settled["subtotal_cents"] == 5500
        assert settled["tax_cents"] == 275
        assert settled["total_cents"] == 5775
