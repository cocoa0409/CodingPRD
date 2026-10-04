"""The cascade an event close drives, from the event down to the order's payment axis."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]


def _unplaced_order(unit_price_cents=900, quantity=1, allocation_units=5,
                    submit=False):
    """One customer order carrying a single line on a live listing.

    With ``submit=False`` the line is still PENDING_AGGREGATION, which is the state the
    event close sweeps up.

    Returns (vendor, event, listing, customer, order, line).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=500,
        allocation_units=allocation_units, ship_time_quote_days=14,
        vendor_sku="NW-CLOS-1")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = TEST_USERS["customer_headers"].copy()
    cust_h["X-User-ID"] = customer["id"]
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity}, cust_h))
    if submit:
        get_success_data(api_client.submit_order(order["id"], cust_h))
    return vendor, event, listing, customer, order, line


def test_event_close_cancels_the_unplaced_line_and_its_order(
        api, merchandiser_headers):
    """PRD §3.1: "At the first hop, every `Confirmation` still in
    `PENDING_AGGREGATION` on the event's listings is set to `CANCELLED` with a
    `cancellation_reason` of `EVENT_CLOSED`. At the second hop, any `CustomerOrder`
    that as a result has every line terminal and at least one `CANCELLED` line is set
    to `CANCELLED`."

    PRD §3.1: "every `Confirmation` on the event's listings must already have left
    `PENDING_AGGREGATION`, unless the caller passes `cancel_pending_aggregations` set
    to true, in which case the unplaced lines are swept up by the close itself."

    Design: Difficulty/transitive_cascade/event_close_three_hop_cascade_to_refund_ledger
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line = _unplaced_order()

    line_before = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_before["confirmation_status"] == "PENDING_AGGREGATION", (
        "the line is unplaced and holds no allocation")

    closed = validate_success(api_client.close_event(
        event["id"], merchandiser_headers,
        {"cancel_pending_aggregations": True}), 200)
    assert closed["event_status"] == "CLOSED"
    assert closed["open_event_for_shop"] is False
    assert closed["closed_at"] is not None

    line_after = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_after["confirmation_status"] == "CANCELLED", (
        f"the unplaced line is swept up by the close, got "
        f"{line_after['confirmation_status']}")

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "CANCELLED", (
        "an order whose every line is terminal and which carries a cancelled line "
        f"follows the second hop, got {order_after['order_status']}")


def test_event_close_refunds_the_uncaptured_authorization(
        api, merchandiser_headers):
    """PRD §3.1: "At the third hop, each such order's `payment_status` becomes
    `REFUNDED`, its `refund_due_cents` is booked into the owning customer's
    `refund_balance_cents`, and a `CreditLedger` row with `source_kind`
    `CANCELLATION` is issued."

    PRD §3.6: "An order whose authorization was never captured behaves differently on
    cancellation: it moves straight from `AUTHORIZED` to `REFUNDED` while the
    captured and refunded amounts both stay 0, since there is nothing to give back."

    Design: Difficulty/transitive_cascade/event_close_three_hop_cascade_to_refund_ledger
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line = _unplaced_order()

    order_before = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_before["payment_status"] == "AUTHORIZED"

    api.close_event(event["id"], merchandiser_headers,
                    {"cancel_pending_aggregations": True})

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "CANCELLED"
    assert order_after["payment_status"] == "REFUNDED", (
        "the payment axis runs from the uncaptured authorization straight to "
        f"REFUNDED, got {order_after['payment_status']}")
    assert order_after["refund_due_cents"] == 0, (
        "the line was never priced, so there is nothing to give back")

    customer_after = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert customer_after["refund_balance_cents"] == 0, (
        "booking a zero refund leaves the balance untouched")