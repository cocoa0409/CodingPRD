"""Validation priority pairs, capacity boundaries, and credit-limit boundary
(queue A priority_pair / boundary_precision; queue B endpoints capacity)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_facility, setup_cxl_dough_type, setup_cafe, set_clock,
    create_order, submit_order, place_and_submit_order,
    create_plan_for_date, lock_plan, release_plan, setup_route, arrive_stop,
    close_plan,
    get_order, get_cafe,
    make_cafe_manager_headers,
)

PLANNER = TEST_USERS["facility_planner_headers"]


def _close_one_day_with_invoice(facility, cafe, cxl, production_date, quantity,
                                order_clock, post_cutoff_clock):
    """Deliver `quantity` units and close the plan so the cafe carries an invoice."""
    place_and_submit_order(cafe, cxl, production_date, quantity,
                           order_clock=order_clock)
    plan = create_plan_for_date(facility, production_date, post_cutoff_clock)
    lock_plan(facility, plan)
    release_plan(facility, plan)
    route, stops = setup_route(
        facility, production_date,
        [{"cafe": cafe, "seq": 1,
          "planned_arrival": f"{production_date}T03:10:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": quantity}],
        vehicle_capacity_units=500, depart=True)
    arrive_stop(facility, route, stops[0], f"{production_date}T03:10:00Z")
    close_plan(facility, plan)


class TestPriorityStateBeatsFiscal:
    def test_amend_locked_order_reports_order_locked_not_credit_limit(self, api):
        """PRD §2.7: "Only after those come the business rules: the locked-order and
        locked-plan guards (`ERR_ORDER_LOCKED`, `ERR_PLAN_LOCKED`), then the
        order-cutoff check (`ERR_ORDER_CUTOFF_PASSED`)" and later "then the
        credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`)".
        PRD §3.2: "any attempt to amend or cancel once the order has reached `LOCKED`
        or beyond is rejected with `ERR_ORDER_LOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_locked_order_credit_breach
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        order = place_and_submit_order(cafe, cxl, "2026-09-10", 100)

        # Move past the CXL cutoff (13:00) so the order auto-locks.
        set_clock("2026-09-09T13:00:01Z")
        assert get_order(order["id"])["status"] == "LOCKED"

        cafe_now = get_cafe(cafe["id"])
        # Amending to 300 units would also breach credit (300 x 4.48 = 134400 > 90000),
        # but the locked-order state gate runs before the fiscal gate.
        resp = api.amend_cafe_order(
            order["id"],
            {"quantity": 300, "expected_cafe_version": cafe_now["version"]},
            make_cafe_manager_headers(cafe["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_LOCKED, 409)

    def test_amend_locked_order_is_rejected_even_with_valid_token(self, api):
        """PRD §3.2: "any attempt to amend or cancel once the order has reached
        `LOCKED` or beyond is rejected with `ERR_ORDER_LOCKED`."
        PRD §3.2: "When the cutoff instant arrives, an auto-lock sweep moves every
        still-`SUBMITTED` order for that dough type and date into `LOCKED` — a
        submission whose cutoff has already passed locks in the same breath. A locked
        order is immutable: the amendment window has closed for good."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_locked_order_credit_breach
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        order = place_and_submit_order(cafe, cxl, "2026-09-10", 100)
        set_clock("2026-09-09T13:00:01Z")
        assert get_order(order["id"])["status"] == "LOCKED"

        cafe_now = get_cafe(cafe["id"])
        resp = api.amend_cafe_order(
            order["id"],
            {"quantity": 150, "expected_cafe_version": cafe_now["version"]},
            make_cafe_manager_headers(cafe["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_LOCKED, 409)
        assert get_order(order["id"])["quantity"] == 100


class TestCapacityBoundary:
    def test_plan_at_exact_capacity_locks(self, api):
        """PRD §3.4: "Locking is only permitted while the plan is `OPEN` and its
        `total_effective_units` is within the facility's `effective_capacity_units`".
        PRD §3.4: "`total_effective_units` is the sum over attached planned lines of
        each line's `adjusted_quantity` weighted by category — one effective unit per
        conventional unit, two per artisan unit. The `over_capacity` flag is set when
        that total exceeds the facility's `effective_capacity_units`."

        Design: Difficulty/boundary_precision_check/capacity_exactly_at_limit_locks_but_one_over_fails
        """
        facility = setup_facility(2000)
        cxl = setup_cxl_dough_type()
        cafes = [
            setup_cafe(facility["id"], "C1", "FRANCHISE", 300000),
            setup_cafe(facility["id"], "C2", "COMPANY", 300000),
            setup_cafe(facility["id"], "C4", "FRANCHISE", 300000),
            setup_cafe(facility["id"], "C5", "FRANCHISE", 300000),
        ]
        for cafe in cafes:
            place_and_submit_order(cafe, cxl, "2026-09-10", 500)

        plan = create_plan_for_date(facility, "2026-09-10")
        assert plan["total_effective_units"] == 2000
        assert plan["over_capacity"] is False

        locked = lock_plan(facility, plan)
        assert locked["status"] == "LOCKED", "== capacity is inclusive: lock succeeds"

    def test_plan_one_over_capacity_cannot_lock(self, api):
        """PRD §3.4: "an over-capacity plan cannot lock at all and the attempt is
        rejected with `ERR_CAPACITY_EXCEEDED`."
        PRD §3.4: "The `over_capacity` flag is set when that total exceeds the
        facility's `effective_capacity_units`."

        Design: Difficulty/boundary_precision_check/capacity_exactly_at_limit_locks_but_one_over_fails
        """
        facility = setup_facility(2000)
        cxl = setup_cxl_dough_type()
        c1 = setup_cafe(facility["id"], "C1", "FRANCHISE", 300000)
        c2 = setup_cafe(facility["id"], "C2", "COMPANY", 300000)
        c4 = setup_cafe(facility["id"], "C4", "FRANCHISE", 300000)
        c5 = setup_cafe(facility["id"], "C5", "FRANCHISE", 300000)
        for cafe in (c1, c2, c4, c5):
            place_and_submit_order(cafe, cxl, "2026-09-10", 500)
        # One extra unit pushes total_effective_units to 2001.
        place_and_submit_order(get_cafe(c1["id"]), cxl, "2026-09-10", 1)

        plan = create_plan_for_date(facility, "2026-09-10")
        assert plan["total_effective_units"] == 2001
        assert plan["over_capacity"] is True

        resp = api.lock_production_plan(facility["id"], plan["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)

    def test_over_capacity_plan_lock_rejected(self, api, planner_headers):
        """PRD §3.4: "an over-capacity plan cannot lock at all and the attempt is
        rejected with `ERR_CAPACITY_EXCEEDED`."

        Design: Corner/endpoints/over_capacity_plan_cannot_lock
        """
        facility = setup_facility(100)
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        place_and_submit_order(cafe, cxl, "2026-09-10", 120)
        plan = create_plan_for_date(facility, "2026-09-10")
        assert plan["total_effective_units"] == 120
        assert plan["over_capacity"] is True

        resp = api.lock_production_plan(facility["id"], plan["id"], planner_headers)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)


class TestCreditLimitBoundary:
    def test_submit_at_exact_credit_limit_passes(self, api):
        """PRD §3.2: "the cafe's current `credit_balance_cents` plus the provisional
        invoice total for the new line must not exceed the cafe's `credit_limit_cents`,
        or the submission is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        41664 + 107 x 4.48 = 89616 <= 90000 — the inclusive side of the boundary.

        Design: Difficulty/boundary_precision_check/credit_limit_exactly_at_limit_passes_one_cent_over_fails
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        _close_one_day_with_invoice(facility, cafe, cxl, "2026-09-10", 93,
                                    "2026-09-09T10:00:00Z", "2026-09-09T13:00:01Z")
        assert get_cafe(cafe["id"])["credit_balance_cents"] == 41664

        set_clock("2026-09-10T10:00:00Z")
        order2 = create_order(cafe, cxl, "2026-09-11", 107)
        submitted = submit_order(cafe, order2)
        assert submitted["status"] == "SUBMITTED"

    def test_submit_one_unit_over_credit_limit_rejected(self, api):
        """PRD §3.2: "the cafe's current `credit_balance_cents` plus the provisional
        invoice total for the new line must not exceed the cafe's `credit_limit_cents`,
        or the submission is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD §3.2: "The provisional total projects the invoice using the order's
        `quantity` (not the adjusted figure) multiplied by the current unit transfer
        price — the same per-unit price the final invoice will use, computed per the
        transfer-pricing rule in §3.8".

        41664 + 108 x 4.48 = 90048 > 90000 — one unit over the limit.

        Design: Difficulty/boundary_precision_check/credit_limit_exactly_at_limit_passes_one_cent_over_fails
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        _close_one_day_with_invoice(facility, cafe, cxl, "2026-09-10", 93,
                                    "2026-09-09T10:00:00Z", "2026-09-09T13:00:01Z")
        assert get_cafe(cafe["id"])["credit_balance_cents"] == 41664

        set_clock("2026-09-10T10:00:00Z")
        order2 = create_order(cafe, cxl, "2026-09-11", 108)
        resp = api.submit_cafe_order(order2["id"], make_cafe_manager_headers(cafe["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)
