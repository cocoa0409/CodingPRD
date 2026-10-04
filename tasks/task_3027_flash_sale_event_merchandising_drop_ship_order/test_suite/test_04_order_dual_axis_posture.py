"""An aggregate order's fulfillment axis and payment axis evolve independently."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def _partially_filled_order(unit_price_cents=400, allocation_units=10,
                            quantity_each=4, confirm_a=2, confirm_b=4):
    """One order carrying two lines on the same listing, bought and closed short so
    that one line is short-shipped and the other is not.

    Returns (vendor, event, listing, customer, order, line_a, line_b, po).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=250,
        allocation_units=allocation_units, ship_time_quote_days=14,
        vendor_sku="NW-A")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = TEST_USERS["customer_headers"].copy()
    cust_h["X-User-ID"] = customer["id"]
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line_a = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity_each}, cust_h))
    line_b = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity_each}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"],
                   "quantity_ordered": quantity_each * 2}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))

    vendor_h = TEST_USERS["vendor_headers"].copy()
    vendor_h["X-User-ID"] = vendor["id"]
    get_success_data(api_client.confirm_line(
        line_a["id"], {"confirm_units": confirm_a}, vendor_h))
    get_success_data(api_client.confirm_line(
        line_b["id"], {"confirm_units": confirm_b}, vendor_h))

    get_success_data(api_client.capture_order(order["id"], PLANNER))
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))
    return vendor, event, listing, customer, order, line_a, line_b, po


def test_close_short_moves_fulfilment_axis_and_marks_only_the_short_line(
        api, merchandiser_headers):
    """PRD §3.6: "an order whose lines were partially short-shipped moves from
    `AWAITING_VENDOR` to `PARTIALLY_FILLED` when at least one line was set
    `SHORT_SHIPPED` by the cascade and at least one line remains in
    `VENDOR_CONFIRMED` or later".

    PRD §3.6: "the line's contribution is the smaller of the sum of those two terms
    and the missing units multiplied by `line_unit_price_cents`. The order's
    `refund_due_cents` is the sum of those per-line contributions over the order's
    non-refunded lines."

    Design: Difficulty/non_linear_state_machine/customer_order_dual_axis_parallel_state
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line_a, line_b, po = \
        _partially_filled_order()

    order_now = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_now["order_status"] == "PARTIALLY_FILLED", (
        f"expected PARTIALLY_FILLED, got {order_now['order_status']}")
    assert order_now["refund_due_cents"] == 800, (
        "two missing units at 400 cents each is 800, got "
        f"{order_now['refund_due_cents']}")

    a = validate_success(api.get_confirmation(line_a["id"], ANY), 200)
    b = validate_success(api.get_confirmation(line_b["id"], ANY), 200)
    assert a["short_shipped_units"] == 2
    assert b["short_shipped_units"] == 0, (
        "a line whose confirmed units reached its quantity is not short-shipped")


def test_money_axis_advances_independently_of_the_fulfilment_axis(
        api, merchandiser_headers):
    """PRD §2.7: "A transition on one axis does not imply a transition on the other.
    An order can be `PARTIALLY_FILLED` in fulfillment while still `CAPTURED` in
    payment, and an order can reach `CROSS_DOCKED` while `payment_status` is
    `PARTIALLY_REFUNDED`. Implementations must treat the pair as a product, not as a
    single ladder."

    Design: Difficulty/non_linear_state_machine/customer_order_dual_axis_parallel_state
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line_a, line_b, po = \
        _partially_filled_order()

    validate_success(api.refund_order(
        order["id"], {"write_off_full_line": False}, PLANNER), 200)

    order_now = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_now["refund_due_cents"] == 0, (
        "the refund must clear the remaining amount owed")
    assert order_now["payment_status"] == "REFUNDED", (
        "the money axis has run to its terminal value")
    assert order_now["order_status"] == "PARTIALLY_FILLED", (
        "the fulfilment axis must be untouched by the refund — the pair "
        "(PARTIALLY_FILLED, REFUNDED) is reachable and no single-axis model "
        f"expresses it, got {order_now['order_status']}")