"""Validation precedence and the exact instants and cents where rules flip.

Each pair here first shows the higher-priority gate masking a lower one, then
removes the mask and shows the lower gate firing on its own; the boundary pair
does the same for the 168-hour capture limit and the 500000-cent fee break.
"""

from test_helpers import (
    ERR_DISPUTED_AMOUNT_EXCEEDS_SUBJECT,
    ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE,
    ERR_LATE_EVENT_REQUIRES_CORRECTION,
    ERR_MOVEMENT_NOT_CLOSED,
    ERR_RECLAIM_WINDOW_OUTSIDE_MOVEMENT,
    AUGUST_BOOTSTRAP,
    OUT_76H,
    ApiClient,
    assert_error_envelope,
    assert_instant_equals,
    assert_money,
    closed_movement_of,
    computed_cycle,
    exchanged_cycle,
    open_movement_of,
    read_cycle,
    register_car,
    register_junction,
    set_clock,
    standard_world,
    three_line_world,
    validate_success,
)
import test_helpers.factories as f

MASKED_WINDOW_FROM = "2026-08-20T00:00:00Z"
MASKED_WINDOW_TO = "2026-08-21T00:00:00Z"


def _bad_ordered_open_segment(api):
    """A CX-owned car in BN's custody, bad-ordered, its BN segment still OPEN."""
    world = standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP,
                           register_first_car=False)
    car_id = register_car(api, "CX 100020", world.xm, world.cx, world=world)
    set_clock(api, OUT_76H, world)
    validate_success(api.create_interchange_event(
        f.delivery_event_payload(car_id, world.jct, world.cx, world.bn, OUT_76H,
                                 12000, "LOADED"),
        world.clerk(world.cx)), 201)
    set_clock(api, "2026-08-27T00:00:00Z", world)
    validate_success(api.report_bad_order(
        car_id, f.bad_order_payload("2026-08-27T00:00:00Z"), world.clerk(world.bn)))
    return world, car_id


def _claims_on(api, world, movement_id):
    rows = validate_success(api.list_reclaim_claims(
        world.accountant(world.bn), params={"movement_id": movement_id}))
    return rows if isinstance(rows, list) else rows["items"]


class TestReclaimGateOrdering:
    """An unclosed segment is reported before the window is measured against it."""

    def test_an_open_segment_reports_not_closed_and_not_the_window_error(self, api: ApiClient):
        """A window six days before an OPEN segment still yields ERR_MOVEMENT_NOT_CLOSED.

        PRD: "The parent segment must be `CLOSED`, otherwise `ERR_MOVEMENT_NOT_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/reclaim_movement_not_closed_at_12_masks_window_outside_movement_at_33
        """
        world, car_id = _bad_ordered_open_segment(api)
        movement = open_movement_of(api, car_id, world.bn, world.accountant(world.bn))
        assert movement["status"] == "OPEN"
        assert_instant_equals(movement["bad_order_from"], "2026-08-27T00:00:00Z",
                              "bad_order_from")

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", MASKED_WINDOW_FROM,
                              MASKED_WINDOW_TO, movement["version"]),
            world.accountant(world.bn),
        )
        assert_error_envelope(refused, ERR_MOVEMENT_NOT_CLOSED, 409)
        assert _claims_on(api, world, movement["id"]) == []

    def test_closing_the_segment_uncovers_the_window_gate(self, api: ApiClient):
        """The identical window on the now-CLOSED segment yields the window error.

        PRD: "It must lie inside the segment: `window_from` at or after the segment's `start_at`, and `window_to` at or before its `end_at`, otherwise `ERR_RECLAIM_WINDOW_OUTSIDE_MOVEMENT`."

        Design: Difficulty/priority_pair_validation_conflict/reclaim_movement_not_closed_at_12_masks_window_outside_movement_at_33
        """
        world, car_id = _bad_ordered_open_segment(api)
        set_clock(api, "2026-08-28T12:00:00Z", world)
        validate_success(api.release_to_service(
            car_id, f.release_payload("2026-08-28T12:00:00Z"), world.clerk(world.bn)))
        set_clock(api, "2026-08-28T18:00:00Z", world)
        validate_success(api.create_interchange_event(
            f.delivery_event_payload(car_id, world.jct, world.bn, world.cx,
                                     "2026-08-28T18:00:00Z", 12300, "LOADED"),
            world.clerk(world.bn)), 201)

        movement = closed_movement_of(api, car_id, world.bn,
                                     world.accountant(world.bn))
        assert movement["status"] == "CLOSED"

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", MASKED_WINDOW_FROM,
                              MASKED_WINDOW_TO, movement["version"]),
            world.accountant(world.bn),
        )
        assert_error_envelope(refused, ERR_RECLAIM_WINDOW_OUTSIDE_MOVEMENT, 422)
        assert _claims_on(api, world, movement["id"]) == []


class TestDisputeSubjectGateOrdering:
    """Membership is checked before the disputed amount is compared to the line."""

    def test_an_out_of_cycle_subject_masks_the_amount_check(self, api: ApiClient):
        """A September segment plus an absurd amount reports only the membership error.

        PRD: "The named subject must belong to the named cycle — its own `settlement_cycle_id` must be that cycle — otherwise `ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE`."

        Design: Difficulty/priority_pair_validation_conflict/dispute_subject_not_in_cycle_at_24_masks_disputed_amount_exceeds_subject_at_54
        """
        world, cars, movements = three_line_world(api, cars=3)
        cycle, computed, exchanged = exchanged_cycle(api, world)

        outsider = register_car(api, "CX 100004", world.xm, world.cx, world=world)
        set_clock(api, "2026-09-02T00:00:00Z", world)
        validate_success(api.create_interchange_event(
            f.delivery_event_payload(outsider, world.jct, world.cx, world.bn,
                                     "2026-09-02T00:00:00Z", 3000, "EMPTY"),
            world.clerk(world.cx)), 201)
        set_clock(api, "2026-09-04T00:00:00Z", world)
        validate_success(api.create_interchange_event(
            f.delivery_event_payload(outsider, world.jct, world.bn, world.cx,
                                     "2026-09-04T00:00:00Z", 3000, "EMPTY"),
            world.clerk(world.bn)), 201)

        september = closed_movement_of(api, outsider, world.bn,
                                      world.accountant(world.bn))
        assert_money(september["net_hire_cents"], 4700, "september net_hire_cents")
        assert september["settlement_cycle_id"] is None

        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "HIRE_RATE_MISAPPLIED", 99999999,
                              exchanged["version"], movement_id=september["id"]),
            world.accountant(world.bn),
        )
        assert_error_envelope(refused, ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE, 422)

        after = read_cycle(api, world, cycle["id"])
        assert after["version"] == exchanged["version"]
        rows = validate_success(api.list_disputes(
            world.accountant(world.bn), params={"settlement_cycle_id": cycle["id"]}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert rows == []

    def test_an_in_cycle_subject_uncovers_the_amount_check(self, api: ApiClient):
        """Re-pointed at the 4700 member line, the same amount reports the excess error.

        PRD: "The server snapshots `subject_net_at_filing_cents` from the subject — the segment's `net_hire_cents` or the bill's `total_cents` — and `disputed_amount_cents` must be greater than 0 and no greater than that snapshot, otherwise `ERR_DISPUTED_AMOUNT_EXCEEDS_SUBJECT`."

        Design: Difficulty/priority_pair_validation_conflict/dispute_subject_not_in_cycle_at_24_masks_disputed_amount_exceeds_subject_at_54
        """
        world, cars, movements = three_line_world(api, cars=3)
        cycle, computed, exchanged = exchanged_cycle(api, world)
        target = next(c for c in cars if movements[c]["net_hire_cents"] == 4700)
        member = validate_success(api.get_movement(movements[target]["id"],
                                                  world.accountant(world.bn)))
        assert member["settlement_cycle_id"] == cycle["id"]

        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "HIRE_RATE_MISAPPLIED", 99999999,
                              exchanged["version"], movement_id=member["id"]),
            world.accountant(world.bn),
        )
        assert_error_envelope(refused, ERR_DISPUTED_AMOUNT_EXCEEDS_SUBJECT, 422)

        after = read_cycle(api, world, cycle["id"])
        assert after["version"] == exchanged["version"]
        rows = validate_success(api.list_disputes(
            world.accountant(world.bn), params={"settlement_cycle_id": cycle["id"]}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert rows == []


LATE_BOOTSTRAP = "2026-08-19T00:00:00Z"
LATE_CLOCK = "2026-08-27T00:00:00Z"
EXACTLY_168H_OLD = "2026-08-20T00:00:00Z"
ONE_HOUR_TOO_OLD = "2026-08-19T23:00:00Z"
INSIDE_THE_LIMIT = "2026-08-20T00:01:00Z"


def _late_capture_world(api):
    """A CX-owned car at home with the clock eight days past its registration."""
    world = standard_world(api, bootstrap_clock=LATE_BOOTSTRAP)
    set_clock(api, LATE_CLOCK, world)
    return world


class TestLateCaptureLimitBoundary:
    """168 hours old is still a capture; 169 hours old must become a correction."""

    def test_an_event_exactly_one_hundred_sixty_eight_hours_old_is_accepted(self, api: ApiClient):
        """A handoff dated exactly 168 hours before the clock is recorded normally.

        PRD: "`interchange_at` must be no more than 168 hours — seven days — older than the logical clock, and the boundary is inclusive: an event exactly 168 hours old is still accepted, while one 168 hours and one minute old is refused with `ERR_LATE_EVENT_REQUIRES_CORRECTION` and must instead enter the log through a confirmed correction of type `MISSED_EVENT_INSERT`, which is exempt from this limit."

        Design: Difficulty/boundary_precision_check/late_event_limit_inclusive_at_exactly_168_hours_and_refused_at_169
        """
        world = _late_capture_world(api)
        event = validate_success(api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     EXACTLY_168H_OLD, 1000, "LOADED"),
            world.clerk(world.cx)), 201)

        assert event["status"] == "RECORDED"
        assert event["source"] == "CLERK_CAPTURE"
        assert_instant_equals(event["interchange_at"], EXACTLY_168H_OLD,
                              "interchange_at")

        segment = open_movement_of(api, world.car, world.bn,
                                  world.accountant(world.bn))
        assert segment["status"] == "OPEN"
        assert_instant_equals(segment["start_at"], EXACTLY_168H_OLD, "start_at")

        car = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car["custody_status"] == "ON_FOREIGN_ROAD"
        assert car["current_handling_road_id"] == world.bn

    def test_one_hour_older_is_refused_while_a_minute_newer_is_accepted(self, api: ApiClient):
        """169 hours old is refused, and 167 hours 59 minutes old goes straight in.

        PRD: "`interchange_at` must be no more than 168 hours — seven days — older than the logical clock, and the boundary is inclusive: an event exactly 168 hours old is still accepted, while one 168 hours and one minute old is refused with `ERR_LATE_EVENT_REQUIRES_CORRECTION` and must instead enter the log through a confirmed correction of type `MISSED_EVENT_INSERT`, which is exempt from this limit."

        Design: Difficulty/boundary_precision_check/late_event_limit_inclusive_at_exactly_168_hours_and_refused_at_169
        """
        world = _late_capture_world(api)
        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     ONE_HOUR_TOO_OLD, 1000, "LOADED"),
            world.clerk(world.cx))
        assert_error_envelope(refused, ERR_LATE_EVENT_REQUIRES_CORRECTION, 422)

        car = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car["custody_status"] == "ON_HOME_ROAD"
        assert car["current_handling_road_id"] == world.cx

        rows = validate_success(api.list_interchange_events(
            world.clerk(world.cx), params={"car_id": world.car}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert rows == []

        accepted = validate_success(api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     INSIDE_THE_LIMIT, 1000, "LOADED"),
            world.clerk(world.cx)), 201)
        assert accepted["status"] == "RECORDED"
        assert_instant_equals(accepted["interchange_at"], INSIDE_THE_LIMIT,
                              "interchange_at")


PREAUTH = "PA-2026-000714"
DEFECT_AT = "2026-08-21T12:00:00Z"


def _repair_only_cycle(api, material_cents: int):
    """One accepted repair bill priced to straddle the fee break, and its cycle.

    An NS-owned car passes NS to BN to CX, so BN holds custody at the defect
    instant while CX does the repair: the bill's payee is CX and its payer BN,
    and no hire segment qualifies for that pair, leaving the repair charge as the
    whole of the basis.
    """
    world = standard_world(api, extra_roads=("NS",))
    register_junction(api, "JCT-DEN", world.ns, world.bn, world)
    car_id = register_car(api, "NS 200001", world.xm, world.ns, world=world)

    set_clock(api, "2026-08-21T00:00:00Z", world)
    validate_success(api.create_interchange_event(
        f.delivery_event_payload(car_id, world.junctions["JCT-DEN"], world.ns,
                                 world.bn, "2026-08-21T00:00:00Z", 100, "LOADED"),
        world.clerk(world.ns)), 201)
    set_clock(api, "2026-08-22T00:00:00Z", world)
    validate_success(api.create_interchange_event(
        f.delivery_event_payload(car_id, world.jct, world.bn, world.cx,
                                 "2026-08-22T00:00:00Z", 200, "LOADED"),
        world.clerk(world.bn)), 201)

    set_clock(api, "2026-08-22T06:00:00Z", world)
    validate_success(api.report_bad_order(
        car_id, f.bad_order_payload("2026-08-22T06:00:00Z"), world.clerk(world.cx)))

    draft = validate_success(api.create_repair_bill(
        f.repair_bill_payload(car_id, world.cx, "R-114", "HANDLING_DAMAGE",
                              DEFECT_AT, 1.0, material_cents,
                              pre_authorization_reference=PREAUTH),
        world.repair(world.cx)), 201)
    bill = validate_success(api.submit_repair_bill(draft["id"], {},
                                                 world.repair(world.cx)))

    set_clock(api, "2026-08-23T00:00:00Z", world)
    accepted = validate_success(api.accept_repair_bill(bill["id"], {},
                                                     world.repair(world.bn)))
    cycle, computed = computed_cycle(api, world)
    return world, accepted, cycle, computed


class TestFeeBreakBoundary:
    """The fee curve steps down as the basis crosses 500000 cents."""

    def test_a_basis_of_exactly_five_hundred_thousand_stays_in_tier_one(self, api: ApiClient):
        """A repair-only basis of exactly 500000 pays 2500 and remits 497500.

        PRD: "The rate is 0.5 percent when the basis is at or below 500000 cents and 0.35 percent when it is above, and the selected rate applies to the whole basis with no blending, so the fee curve steps *down* as the basis crosses the break: a basis of 499999 yields 2500, a basis of exactly 500000 also yields 2500 because the break is still tier one, and a basis of 500001 yields 1750 — one cent more basis, 750 cents less fee."

        Design: Difficulty/boundary_precision_check/clearinghouse_fee_steps_down_at_exactly_500000_cents_of_pre_fee_net
        """
        world, bill, cycle, computed = _repair_only_cycle(api, 455616)

        assert bill["responsibility_rule_applied"] == "HANDLING_LINE_RULE"
        assert bill["responsible_road_id"] == world.bn
        assert bill["billing_road_id"] == world.cx
        assert_money(bill["labor_cents"], 9500, "labor_cents")
        assert_money(bill["subtotal_cents"], 465116, "subtotal_cents")
        assert_money(bill["handling_fee_cents"], 34884, "handling_fee_cents")
        assert_money(bill["total_cents"], 500000, "total_cents")

        assert computed["movement_line_count"] == 0
        assert_money(computed["gross_hire_cents"], 0, "gross_hire_cents")
        assert_money(computed["repair_charge_cents"], 500000, "repair_charge_cents")
        assert_money(computed["pre_fee_net_cents"], 500000, "pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 2500, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 497500, "net_settlement_cents")

    def test_one_cent_more_basis_drops_the_fee_by_seven_hundred_fifty(self, api: ApiClient):
        """A basis of 500001 pays only 1750 and remits 498251.

        PRD: "**The clearinghouse fee is a flat selected rate, not a marginal ladder.** Its basis is the absolute value of `pre_fee_net_cents` — the net *before* the fee, never `net_settlement_cents`, since feeding the post-fee figure back would be circular."

        Design: Difficulty/boundary_precision_check/clearinghouse_fee_steps_down_at_exactly_500000_cents_of_pre_fee_net
        """
        world, bill, cycle, computed = _repair_only_cycle(api, 455617)

        assert_money(bill["subtotal_cents"], 465117, "subtotal_cents")
        assert_money(bill["handling_fee_cents"], 34884, "handling_fee_cents")
        assert_money(bill["total_cents"], 500001, "total_cents")

        assert_money(computed["repair_charge_cents"], 500001, "repair_charge_cents")
        assert_money(computed["pre_fee_net_cents"], 500001, "pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 1750, "clearinghouse_fee_cents")
        assert computed["clearinghouse_fee_cents"] < 2500
        assert_money(computed["net_settlement_cents"], 498251, "net_settlement_cents")
