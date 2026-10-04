"""Transitive cascades: route-cancel depth-3 chain and plan-close depth-2 chain
(queue A transitive_cascade)."""
from test_helpers import (
    validate_success, get_success_data,
    setup_facility, setup_cxl_dough_type, setup_bmt_dough_type, setup_cafe,
    place_and_submit_order, create_plan_for_date, lock_plan, release_plan,
    setup_route, close_plan,
    get_order, get_cafe, get_plan, get_route, get_stop,
)


def _setup_c3_c5_published_route(api):
    """C3 50 BMT + C5 150 CXL & 60 BMT planned for 2026-09-11; plan locked and
    released; route PUBLISHED (not departed) with stops for C3 and C5."""
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
    return {"facility": facility, "cxl": cxl, "bmt": bmt, "c3": c3, "c5": c5,
            "o_c3": o_c3, "o_c5": o_c5, "o_c5b": o_c5b,
            "plan": plan, "route": route, "stops": stops}


class TestRouteCancelCascade:
    def test_route_cancel_cascades_stops_orders_and_credits(self, api, dispatcher_headers):
        """PRD §3.5: "Cancelling a route cascades: every stop moves to `CANCELLED`;
        every order attached to those stops moves to `CANCELLED` regardless of
        whether it was `DRAFT`, `SUBMITTED`, `LOCKED`, `PLANNED`, or `ROUTED`; and
        each cancelled order's `billing_status` is forced to `CREDITED` with a zero
        invoice — there is no charge for an undelivered day, so the cafe's
        `credit_balance_cents` is left unchanged by the cascade."

        Design: Difficulty/transitive_cascade/route_cancel_depth3_stop_order_invoice_credit
        """
        s = _setup_c3_c5_published_route(api)

        resp = api.cancel_route(s["facility"]["id"], s["route"]["id"], dispatcher_headers)
        validate_success(resp, 200)

        assert get_route(s["route"]["id"])["status"] == "CANCELLED"
        # hop 1: stops cancelled
        assert get_stop(s["stops"][0]["id"])["status"] == "CANCELLED"
        assert get_stop(s["stops"][1]["id"])["status"] == "CANCELLED"
        # hop 2: orders cancelled
        for key in ("o_c3", "o_c5", "o_c5b"):
            assert get_order(s[key]["id"])["status"] == "CANCELLED"
        # hop 3: billing forced to CREDITED (zero invoice)
        for key in ("o_c3", "o_c5", "o_c5b"):
            assert get_order(s[key]["id"])["billing_status"] == "CREDITED"
        # zero invoice: cafe balances unchanged
        assert get_cafe(s["c3"]["id"])["credit_balance_cents"] == 0
        assert get_cafe(s["c5"]["id"])["credit_balance_cents"] == 0

    def test_route_cancel_leaves_plan_effective_units_at_zero(self, api, dispatcher_headers):
        """PRD §3.5: "Cancelling a route cascades: every stop moves to `CANCELLED`;
        every order attached to those stops moves to `CANCELLED` regardless of
        whether it was `DRAFT`, `SUBMITTED`, `LOCKED`, `PLANNED`, or `ROUTED`".
        PRD §3.4: "`total_effective_units` is the sum over attached planned lines of
        each line's `adjusted_quantity` weighted by category — one effective unit
        per conventional unit, two per artisan unit."

        Design: Difficulty/transitive_cascade/route_cancel_depth3_stop_order_invoice_credit
        """
        s = _setup_c3_c5_published_route(api)
        # pre-cancel: 150 conv x1 + 110 artisan x2 = 370
        assert get_plan(s["plan"]["id"])["total_effective_units"] == 370

        api.cancel_route(s["facility"]["id"], s["route"]["id"], dispatcher_headers)
        assert get_plan(s["plan"]["id"])["total_effective_units"] == 0
        assert get_cafe(s["c3"]["id"])["credit_balance_cents"] == 0
        assert get_cafe(s["c5"]["id"])["credit_balance_cents"] == 0


class TestPlanCloseCascade:
    def test_plan_close_invoices_orders_and_debits_cafe_balances(self, api):
        """PRD §3.4: "Close creates one invoice line per delivered or shipped-short
        order using the transfer-pricing rule of §3.8, flips each billed order's
        `billing_status` from `UNBILLED` to `INVOICED`, and adds each invoice total
        to the ordering cafe's `credit_balance_cents`."
        PRD §3.6: "Note that an order's `billing_status` does not move at delivery —
        it stays `UNBILLED` until the plan's close invoices the day."

        Design: Difficulty/transitive_cascade/plan_close_order_invoice_cafe_balance
        """
        from test_helpers import setup_two_cafe_released_day
        day = setup_two_cafe_released_day()

        # before close: delivery alone does not debit
        assert get_order(day["o_c1"]["id"])["billing_status"] == "UNBILLED"
        assert get_cafe(day["c1"]["id"])["credit_balance_cents"] == 0

        close_plan(day["facility"], day["plan"])

        # hop 1: both orders invoiced
        assert get_order(day["o_c1"]["id"])["billing_status"] == "INVOICED"
        assert get_order(day["o_c3"]["id"])["billing_status"] == "INVOICED"
        # hop 2: ledger sync on the cafes
        assert get_cafe(day["c1"]["id"])["credit_balance_cents"] == 80640
        assert get_cafe(day["c3"]["id"])["credit_balance_cents"] == 29500

    def test_plan_close_moves_billing_for_every_terminal_order(self, api):
        """PRD §3.4: "It is permitted only when the plan is `RELEASED` and every
        attached order has reached a terminal state — `DELIVERED`, `SHIPPED_SHORT`,
        or `CANCELLED`. Close creates one invoice line per delivered or shipped-short
        order using the transfer-pricing rule of §3.8, flips each billed order's
        `billing_status` from `UNBILLED` to `INVOICED`, and adds each invoice total
        to the ordering cafe's `credit_balance_cents`."

        Design: Difficulty/transitive_cascade/plan_close_order_invoice_cafe_balance
        """
        from test_helpers import setup_two_cafe_released_day
        day = setup_two_cafe_released_day()

        closed = close_plan(day["facility"], day["plan"])
        assert closed["status"] == "CLOSED"
        assert get_order(day["o_c1"]["id"])["billing_status"] == "INVOICED"
        assert get_order(day["o_c3"]["id"])["billing_status"] == "INVOICED"
        assert get_cafe(day["c1"]["id"])["credit_balance_cents"] == 80640
        assert get_cafe(day["c3"]["id"])["credit_balance_cents"] == 29500
