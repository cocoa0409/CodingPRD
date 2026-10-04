"""Donation credits, payment waterfall, and ledger reconciliation
(queue A compensating_invariant; queue B calculations, cross_cutting_layers)."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_facility, setup_cxl_dough_type, setup_cafe, set_clock,
    create_order, submit_order, place_and_submit_order,
    setup_single_cafe_day, setup_closed_schedule, setup_open_schedule,
    log_pickup, confirm_pickup, get_pickup, get_cafe, get_order,
    create_plan_for_date, lock_plan, release_plan, setup_route, arrive_stop,
    close_plan,
    make_cafe_manager_headers,
)

PLANNER = TEST_USERS["facility_planner_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


def _close_day_with_invoice(facility, cafe, cxl, production_date, quantity,
                            order_clock, post_cutoff_clock):
    """Deliver `quantity` units for `production_date` and close the plan, leaving
    the order INVOICED."""
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
    return plan


class TestCafeVersionCompensation:
    def test_create_submit_amend_cancel_cycle_leaves_balance_at_zero(self, api):
        """PRD §3.1: "The system-maintained `credit_balance_cents` starts at 0 when
        the cafe is created and thereafter tracks the outstanding receivable: invoice
        totals are added when a plan close bills the day, payments subtract from it,
        and donation credits subtract from it but can never push it below zero."
        PRD §3.2: "Creating the order touches the cafe aggregate, so the cafe's
        `version` increments by 1."
        PRD §3.2: "Both amendment and cancellation increment the cafe's `version` by 1".

        Design: Difficulty/compensating_invariant/cafe_version_returns_to_baseline_after_amend_cycle
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        v0 = cafe["version"]
        mgr = make_cafe_manager_headers(cafe["id"])

        set_clock("2026-09-09T10:00:00Z")
        order = create_order(cafe, cxl, "2026-09-10", 100)      # +1
        submit_order(cafe, order)                                # +1
        cafe_now = get_cafe(cafe["id"])
        validate_success(api.amend_cafe_order(
            order["id"],
            {"quantity": 80, "expected_cafe_version": cafe_now["version"]},
            mgr), 200)                                           # +1
        validate_success(api.cancel_cafe_order(order["id"], mgr), 200)  # +1

        final = get_cafe(cafe["id"])
        assert final["credit_balance_cents"] == 0, \
            "forward create+submit+amend compensated by cancel leaves the ledger unchanged"
        assert final["version"] == v0 + 4, \
            "four mutations (create, submit, amend, cancel) each bumped version exactly once"
        assert get_order(order["id"])["status"] == "CANCELLED"

    def test_cafe_version_bumps_once_per_order_mutation(self, api):
        """PRD §3.2: "A successful submission moves the order to `SUBMITTED` and
        increments the cafe's `version`."
        PRD §3.2: "Both amendment and cancellation increment the cafe's `version` by 1".

        Design: Difficulty/compensating_invariant/cafe_version_returns_to_baseline_after_amend_cycle
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        v0 = cafe["version"]
        mgr = make_cafe_manager_headers(cafe["id"])

        set_clock("2026-09-09T10:00:00Z")
        order = create_order(cafe, cxl, "2026-09-10", 100)
        assert get_cafe(cafe["id"])["version"] == v0 + 1
        submit_order(cafe, order)
        assert get_cafe(cafe["id"])["version"] == v0 + 2
        cafe_now = get_cafe(cafe["id"])
        validate_success(api.amend_cafe_order(
            order["id"], {"quantity": 80,
                          "expected_cafe_version": cafe_now["version"]}, mgr), 200)
        assert get_cafe(cafe["id"])["version"] == v0 + 3
        validate_success(api.cancel_cafe_order(order["id"], mgr), 200)
        final = get_cafe(cafe["id"])
        assert final["version"] == v0 + 4
        assert final["credit_balance_cents"] == 0


class TestPlanEffectiveUnitsCompensation:
    def test_route_cancel_returns_plan_effective_units_to_zero(self, api, dispatcher_headers):
        """PRD §3.4: "`total_effective_units` is the sum over attached planned lines
        of each line's `adjusted_quantity` weighted by category — one effective unit
        per conventional unit, two per artisan unit."
        PRD §3.5: "Cancelling a route cascades: every stop moves to `CANCELLED`;
        every order attached to those stops moves to `CANCELLED` regardless of
        whether it was `DRAFT`, `SUBMITTED`, `LOCKED`, `PLANNED`, or `ROUTED`; and
        each cancelled order's `billing_status` is forced to `CREDITED` with a zero
        invoice".

        Design: Difficulty/compensating_invariant/production_plan_effective_units_zero_after_route_cancel
        """
        from test_helpers import setup_bmt_dough_type, get_plan
        facility = setup_facility(2000)
        cxl = setup_cxl_dough_type()
        bmt = setup_bmt_dough_type()
        c3 = setup_cafe(facility["id"], "C3", "COMPANY", 90000)
        c5 = setup_cafe(facility["id"], "C5", "FRANCHISE", 100000)

        o_c3 = place_and_submit_order(c3, bmt, "2026-09-11", 50,
                                      order_clock="2026-09-10T09:00:00Z")
        o_c5 = place_and_submit_order(c5, cxl, "2026-09-11", 150,
                                      order_clock="2026-09-10T09:00:00Z")
        o_c5b = place_and_submit_order(c5, bmt, "2026-09-11", 60,
                                       order_clock="2026-09-10T09:00:00Z")

        plan = create_plan_for_date(facility, "2026-09-11", "2026-09-10T18:00:00Z")
        # 50x2 + 150x1 + 60x2 = 370
        assert plan["total_effective_units"] == 370
        lock_plan(facility, plan)
        release_plan(facility, plan)
        route, stops = setup_route(
            facility, "2026-09-11",
            [{"cafe": c3, "seq": 1, "planned_arrival": "2026-09-11T03:30:00Z",
              "window_start_local": "03:00", "window_end_local": "04:00",
              "planned_units": 50},
             {"cafe": c5, "seq": 2, "planned_arrival": "2026-09-11T03:50:00Z",
              "window_start_local": "03:00", "window_end_local": "04:00",
              "planned_units": 210}],
            vehicle_capacity_units=1000, depart=False)

        validate_success(api.cancel_route(facility["id"], route["id"], dispatcher_headers),
                         200)
        assert get_plan(plan["id"])["total_effective_units"] == 0, \
            "compensating cancel conserves capacity"
        for order in (o_c3, o_c5, o_c5b):
            o = get_order(order["id"])
            assert o["status"] == "CANCELLED"
            assert o["billing_status"] == "CREDITED"

    def test_plan_effective_units_weight_artisan_double(self, api):
        """PRD §3.4: "`total_effective_units` is the sum over attached planned lines
        of each line's `adjusted_quantity` weighted by category — one effective unit
        per conventional unit, two per artisan unit."

        Design: Difficulty/compensating_invariant/production_plan_effective_units_zero_after_route_cancel
        """
        from test_helpers import setup_bmt_dough_type
        facility = setup_facility(2000)
        cxl = setup_cxl_dough_type()
        bmt = setup_bmt_dough_type()
        c3 = setup_cafe(facility["id"], "C3", "COMPANY", 90000)
        c5 = setup_cafe(facility["id"], "C5", "FRANCHISE", 100000)

        place_and_submit_order(c3, bmt, "2026-09-11", 50,
                               order_clock="2026-09-10T09:00:00Z")
        place_and_submit_order(c5, cxl, "2026-09-11", 150,
                               order_clock="2026-09-10T09:00:00Z")
        place_and_submit_order(c5, bmt, "2026-09-11", 60,
                               order_clock="2026-09-10T09:00:00Z")

        plan = create_plan_for_date(facility, "2026-09-11", "2026-09-10T18:00:00Z")
        assert plan["total_effective_units"] == 370
        assert plan["over_capacity"] is False


class TestDonationCredit:
    def test_donation_credit_prices_artisan_at_conventional_rate(self, api):
        """PRD §3.9: "Confirmation computes the donation credit: the total unsold
        units — conventional plus artisan — multiplied by the facility's reference
        conventional dough type's `flat_transfer_price`, multiplied by one quarter
        (a 0.25 credit rate), rounded half-up to 2 decimal places."
        PRD §3.9: "Note the asymmetry: the credit always prices at the conventional
        rate even when the unsold units are artisan."

        (20 + 8) x 4.00 x 0.25 = 28.00

        Design: Corner/calculations/donation_credit_rounding_and_reference_price
        """
        facility = setup_facility()
        setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        schedule = setup_closed_schedule(cafe, business_date="2026-09-10",
                                         open_clock="2026-09-10T08:00:00Z")
        pickup = log_pickup(cafe, schedule, unsold_conventional=20, unsold_artisan=8)
        confirmed = confirm_pickup(cafe, pickup)
        assert confirmed["credit_amount"] == 28.00
        assert confirmed["status"] == "CONFIRMED"

    def test_payment_waterfall_oldest_first_partial_remainder(self, api):
        """PRD §3.8: "The payment applies oldest-first across the cafe's `INVOICED`
        orders, ordered by order `created_at` (ties are impossible — server
        timestamps are unique): each order becomes `PAID` only when its invoice is
        fully covered, and a partial remainder stays on the oldest partially paid
        order, which remains `INVOICED`."
        PRD §3.8: "The posting subtracts the amount from the cafe's
        `credit_balance_cents`, increments the cafe's `version`, and returns the
        `applied_cents`, the list of `settled_order_ids`, and the resulting
        `credit_balance_cents`."

        O1 = 100 x 4.48 = 44800 (older); O2 = 93 x 4.48 = 41664 (newer);
        balance 86464. A 50000 payment covers O1 fully and 5200 of O2.

        Design: Corner/calculations/payment_waterfall_oldest_first_partial_remainder
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 200000)

        _close_day_with_invoice(facility, cafe, cxl, "2026-09-09", 100,
                                "2026-09-08T10:00:00Z", "2026-09-08T13:00:01Z")
        plan2 = _close_day_with_invoice(facility, cafe, cxl, "2026-09-10", 93,
                                        "2026-09-09T10:00:00Z", "2026-09-09T13:00:01Z")
        assert get_cafe(cafe["id"])["credit_balance_cents"] == 86464

        # Identify the two INVOICED orders by created order.
        orders, _meta = _list_orders(api, cafe)
        assert len(orders) == 2
        o1_id, o2_id = orders[0]["id"], orders[1]["id"]

        result = validate_success(
            api.post_payment(cafe["id"], {"amount_cents": 50000}, FINANCE), 201)
        assert get_order(o1_id)["billing_status"] == "PAID"
        assert get_order(o2_id)["billing_status"] == "INVOICED"
        assert get_cafe(cafe["id"])["credit_balance_cents"] == 36464
        assert result["credit_balance_cents"] == 36464


def _list_orders(api, cafe):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api.list_cafe_orders(PLANNER, params={"cafe_id": cafe["id"]}))


class TestLedgerReconciliation:
    def test_credit_balance_after_invoice_payment_donation(self, api):
        """PRD §3.1: "invoice totals are added when a plan close bills the day,
        payments subtract from it, and donation credits subtract from it but can
        never push it below zero."
        PRD §3.9: "The credit then reduces the cafe's `credit_balance_cents`, floored
        at zero, and increments the cafe's `version`."

        100 x 4.48 = 44800 invoice; 20000 payment; 12 conv unsold x 4.00 x 0.25 =
        12.00 credit (1200 cents). Final balance 23600.

        Design: Corner/cross_cutting_layers/derived_credit_balance_reconciles_after_invoice_payment_donation
        """
        day = setup_single_cafe_day(quantity=100, close_plan_too=True)
        cafe_id = day["cafe"]["id"]
        assert get_cafe(cafe_id)["credit_balance_cents"] == 44800

        validate_success(api.post_payment(cafe_id, {"amount_cents": 20000}, FINANCE), 201)
        assert get_cafe(cafe_id)["credit_balance_cents"] == 24800

        schedule = setup_closed_schedule(day["cafe"], business_date="2026-09-10",
                                         open_clock="2026-09-10T08:00:00Z")
        pickup = log_pickup(day["cafe"], schedule, unsold_conventional=12,
                            unsold_artisan=0)
        confirmed = confirm_pickup(day["cafe"], pickup)
        assert confirmed["credit_amount"] == 12.00
        assert get_cafe(cafe_id)["credit_balance_cents"] == 23600
