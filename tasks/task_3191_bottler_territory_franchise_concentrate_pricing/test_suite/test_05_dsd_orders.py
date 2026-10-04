"""DSD orders: per-line invoice rounding and cross-dimension preconditions."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    get_success_data,
    seed_active_agreement,
    create_customer,
    create_dsd_order,
    ops_headers,
    make_customer_manager_headers,
)

PA = TEST_USERS["platform_admin_headers"]


def test_dsd_invoice_per_line_rounding_beats_sum_then_round(api):
    """PRD §3.4: "The invoice total is computed with a pinned rounding order —
    per line first, then summed."
    PRD §3.4: "Summing raw amounts and rounding once at the end is forbidden;
    it produces different cents than the pinned order (two lines each raw at
    100.7 cents sum-first to 201 but per-line to 202)."

    Design: Difficulty/combinatorial_formula/dsd_invoice_per_line_rounding_beats_sum_then_round
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=106)
    lines = [
        {"product_line_id": env["line"]["id"], "quantity_cases": 1, "discount_pct": 0.05},
        {"product_line_id": env["line"]["id"], "quantity_cases": 1, "discount_pct": 0.05},
    ]
    order = create_dsd_order(env, cust, lines=lines)
    # per line: round_half_up(106 * 0.95) = round_half_up(100.7) = 101; total 202
    assert order["invoice_total_cents"] == 202
    assert order["invoice_total_cents"] != 201


def test_dsd_invoice_uses_customer_bound_price(api):
    """PRD §3.4: "For each line, the unit price in cents is the customer's
    current `bound_price_cents` (NCA-bound national price or local list
    price)."
    PRD §3.4: "That unit price is multiplied by the line's `quantity_cases` and
    by one minus the line's `discount_pct`, and the result is rounded half-up
    to whole cents to produce the line amount. The order's
    `invoice_total_cents` is the integer sum of those per-line amounts."

    Design: Difficulty/combinatorial_formula/dsd_invoice_per_line_rounding_beats_sum_then_round
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=190)
    order = create_dsd_order(
        env, cust,
        lines=[{"product_line_id": env["line"]["id"], "quantity_cases": 2, "discount_pct": 0}],
    )
    assert order["invoice_total_cents"] == 380


def test_dsd_pay_before_deliver_rejected(api):
    """PRD §3.4: "A `CustomerManager` **pays** an order, moving payment from
    `UNPAID` to `PAID`, but only once fulfillment has reached `DELIVERED`;
    paying earlier is rejected with `ERR_DSD_ORDER_NOT_DELIVERED` (HTTP 409)."

    Design: Corner/state_machines/dsd_pay_before_deliver_rejected
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=190)
    order = create_dsd_order(env, cust)
    r = api_client.pay_dsd_order(order["id"], make_customer_manager_headers(cust["id"]))
    validate_error(r, ApiErrorId.ERR_DSD_ORDER_NOT_DELIVERED.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_dsd_order(order["id"], PA))
    assert after["payment_status"] == "UNPAID"
    assert after["fulfillment_status"] == "BOOKED"


def test_deliver_to_disputed_customer_rejected(api):
    """PRD §3.4: "A `BottlerOps` operator **delivers** a `BOOKED` order, but
    only while the customer is `ACTIVE` — attempting delivery for a `DISPUTED`
    customer is rejected with `ERR_CUSTOMER_DISPUTED` (HTTP 409)."

    Design: Corner/state_machines/deliver_to_disputed_customer_rejected
    """
    env = seed_active_agreement()
    cust = create_customer(env, local_price_cents=190)
    order = create_dsd_order(env, cust)
    r = api_client.dispute_customer(cust["id"], make_customer_manager_headers(cust["id"]))
    assert r.status_code == 200
    r = api_client.deliver_dsd_order(order["id"], ops_headers(env))
    validate_error(r, ApiErrorId.ERR_CUSTOMER_DISPUTED.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_dsd_order(order["id"], PA))
    assert after["fulfillment_status"] == "BOOKED"


def test_not_found_beats_state_check_on_missing_order(api):
    """PRD §2.7: "(3) existence of every path identifier and every foreign-key
    identifier in the body — validated left to right, path parameters first and
    then body fields in their declared order — with any miss rejected as
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)".
    PRD §2.7: "The system applies validations in a fixed priority order on
    every request, and a request fails at the first failing check."

    Design: Corner/validations/not_found_beats_state_check_on_missing_order
    """
    set_clock = api_client.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, PA)
    assert set_clock.status_code == 200
    r = api_client.deliver_dsd_order(NON_EXISTENT_UUID, TEST_USERS["bottler_ops_headers"])
    validate_error(r, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
    assert r.status_code == 404
