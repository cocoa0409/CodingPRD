"""CafeOrder status and billing_status evolve independently (queue A non_linear),
plus state-transition guards (queue B state_machines)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_facility, setup_cxl_dough_type, setup_cafe, set_clock,
    create_order, submit_order, place_and_submit_order, get_order, get_cafe,
    setup_single_cafe_day,
    make_cafe_manager_headers,
)


class TestParallelAxes:
    def test_delivery_does_not_invoice_until_plan_close(self, api, planner_headers, finance_headers):
        """PRD §3.6: "Note that an order's `billing_status` does not move at delivery
        — it stays `UNBILLED` until the plan's close invoices the day."
        PRD §3.8: "Each invoice flips the order's `billing_status` from `UNBILLED` to
        `INVOICED` and adds the invoice total to the cafe's `credit_balance_cents`."
        PRD §3.8: "The payment applies oldest-first across the cafe's `INVOICED`
        orders, ordered by order `created_at` (ties are impossible — server
        timestamps are unique): each order becomes `PAID` only when its invoice is
        fully covered, and a partial remainder stays on the oldest partially paid
        order, which remains `INVOICED`."

        Design: Difficulty/non_linear_state_machine/cafe_order_status_billing_parallel_axes
        """
        day = setup_single_cafe_day(quantity=100, close_plan_too=False)
        order_id = day["order"]["id"]

        order = get_order(order_id)
        assert order["status"] == "DELIVERED"
        assert order["billing_status"] == "UNBILLED", \
            "delivery alone does not invoice: axes evolve independently"

        from test_helpers import close_plan
        close_plan(day["facility"], day["plan"])
        order = get_order(order_id)
        assert order["status"] == "DELIVERED"
        assert order["billing_status"] == "INVOICED"
        assert get_cafe(day["cafe"]["id"])["credit_balance_cents"] == 44800

        validate_success(
            api.post_payment(day["cafe"]["id"], {"amount_cents": 44800}, finance_headers),
            201)
        order = get_order(order_id)
        assert order["status"] == "DELIVERED"
        assert order["billing_status"] == "PAID", \
            "billing axis advanced to PAID while status never left DELIVERED"

    def test_paid_order_remains_delivered(self, api, planner_headers, finance_headers):
        """PRD §3.8: "Each invoice flips the order's `billing_status` from `UNBILLED`
        to `INVOICED` and adds the invoice total to the cafe's
        `credit_balance_cents`."
        PRD §3.8: "each order becomes `PAID` only when its invoice is fully covered,
        and a partial remainder stays on the oldest partially paid order, which
        remains `INVOICED`."

        Design: Difficulty/non_linear_state_machine/cafe_order_status_billing_parallel_axes
        """
        day = setup_single_cafe_day(quantity=100, close_plan_too=True)
        order_id = day["order"]["id"]
        order = get_order(order_id)
        assert order["status"] == "DELIVERED"
        assert order["billing_status"] == "INVOICED"

        validate_success(
            api.post_payment(day["cafe"]["id"], {"amount_cents": 44800}, finance_headers),
            201)
        order = get_order(order_id)
        assert order["billing_status"] == "PAID"
        assert order["status"] == "DELIVERED"


class TestStateTransitionGuards:
    def test_submit_from_submitted_returns_invalid_state(self, api, planner_headers):
        """PRD §2.7: "then whether the target resource's current state permits the
        requested transition (`ERR_INVALID_STATE`)".
        PRD §3.2: "Submitting a `DRAFT` order is the point of commitment, and it is
        where three independent gates fire."

        Design: Corner/state_machines/submit_from_submitted_returns_invalid_state
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        order = place_and_submit_order(cafe, cxl, "2026-09-10", 10)
        assert order["status"] == "SUBMITTED"

        resp = api.submit_cafe_order(order["id"], make_cafe_manager_headers(cafe["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_terminal_order_lockdown_no_further_transitions(self, api, planner_headers):
        """PRD §2.7: "then whether the target resource's current state permits the
        requested transition (`ERR_INVALID_STATE`)".
        PRD §3.2: "Cancellation is available while the order is `DRAFT` or
        `SUBMITTED` and moves it to the terminal `CANCELLED` state."

        Design: Corner/state_machines/terminal_order_lockdown_no_further_transitions
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        set_clock("2026-09-09T10:00:00Z")
        order = create_order(cafe, cxl, "2026-09-10", 10)
        validate_success(
            api.cancel_cafe_order(order["id"], make_cafe_manager_headers(cafe["id"])), 200)
        assert get_order(order["id"])["status"] == "CANCELLED"

        resp = api.submit_cafe_order(order["id"], make_cafe_manager_headers(cafe["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
