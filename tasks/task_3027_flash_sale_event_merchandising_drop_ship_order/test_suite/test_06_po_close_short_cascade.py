"""The four-hop cascade a close-short drives, from the buy down to the refund."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def _cascade_scenario(unit_price_cents=300, quantity=6, confirm_units=4,
                      allocation_units=10):
    """One order line of six units, bought and confirmed for four, then short.

    Returns (vendor, event, listing, customer, order, line, po).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=180,
        allocation_units=allocation_units, ship_time_quote_days=14,
        vendor_sku="NW-CAS-1")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = TEST_USERS["customer_headers"].copy()
    cust_h["X-User-ID"] = customer["id"]
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": quantity},
        PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    vendor_h = TEST_USERS["vendor_headers"].copy()
    vendor_h["X-User-ID"] = vendor["id"]
    get_success_data(api_client.confirm_line(
        line["id"], {"confirm_units": confirm_units}, vendor_h))
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))
    return vendor, event, listing, customer, order, line, po


def test_close_short_cascade_marks_the_line_short_and_the_order_partially_filled(
        api, merchandiser_headers):
    """PRD §3.6: "At the second hop, every `Confirmation` covering those listings
    whose `confirmed_units` is below its `quantity` moves to `SHORT_SHIPPED` with
    `short_shipped_units` set to `quantity` minus `confirmed_units`."

    PRD §3.6: "And at the fourth hop, any order left holding a short line that has
    not shipped, and otherwise complete, moves into `PARTIALLY_FILLED`."

    Design: Difficulty/transitive_cascade/po_close_short_four_hop_cascade_to_refund
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line, po = _cascade_scenario()

    po_now = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_now["po_status"] == "CLOSED_SHORT"
    assert po_now["closed_at"] is not None

    line_now = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_now["confirmation_status"] == "SHORT_SHIPPED"
    assert line_now["short_shipped_units"] == 2, (
        f"6 ordered minus 4 confirmed is 2, got {line_now['short_shipped_units']}")

    order_now = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_now["order_status"] == "PARTIALLY_FILLED", (
        f"the order's fulfilment posture moved, got {order_now['order_status']}")
    assert order_now["refund_due_cents"] == 600, (
        "two missing units at 300 cents each is 600, got "
        f"{order_now['refund_due_cents']}")


def test_cascade_names_the_refund_without_settling_it_until_a_refund_is_issued(
        api, merchandiser_headers):
    """PRD §3.6: "At the third hop, each affected order's `refund_due_cents` and
    `order_total_cents` are recomputed".

    PRD §3.6: "Each refund writes one `CreditLedger` row per refunded line with
    `source_kind` `OVERSELL` or `SHORT_SHIP`, adds the refunded amount to the
    customer's `refund_balance_cents`, and recomputes `refund_due_cents` in the
    selected `variant`."

    Design: Difficulty/transitive_cascade/po_close_short_four_hop_cascade_to_refund
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line, po = _cascade_scenario()

    customer_before = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert customer_before["refund_balance_cents"] == 0, (
        "the cascade names the refund but does not settle it")

    order_after_refund = validate_success(api.refund_order(
        order["id"], {"write_off_full_line": False}, TEST_USERS["inventory_planner_headers"]), 200)
    assert order_after_refund["payment_status"] == "REFUNDED", (
        "the money axis runs to its terminal value once nothing further is owed")
    assert order_after_refund["refund_due_cents"] == 0

    customer_after = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert customer_after["refund_balance_cents"] == 600, (
        "the 600 cents named at hop three becomes bookable once the refund is "
        f"issued, got {customer_after['refund_balance_cents']}")