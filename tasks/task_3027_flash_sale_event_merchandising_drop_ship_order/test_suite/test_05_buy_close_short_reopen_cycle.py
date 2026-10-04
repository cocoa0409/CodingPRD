"""A buy's cyclic path through CLOSED_SHORT back to ISSUED."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def _short_buy_with_confirmed_line(quantity=10, confirm_units=4,
                                   unit_price_cents=200):
    """One submitted 10-unit line, bought and partly confirmed, then closed short.

    Returns (vendor, event, listing, customer, order, line, po).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=120,
        allocation_units=20, ship_time_quote_days=14, vendor_sku="NW-REOPEN")

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
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))
    return vendor, event, listing, customer, order, line, po


def test_close_short_freezes_the_buy_and_records_the_miss_on_the_vendor(
        api, merchandiser_headers):
    """PRD §3.6: "The buy moves to `CLOSED_SHORT`, its `fill_rate_pct` is frozen at
    the ratio of shipped to ordered units, `closed_at` is stamped, and the vendor's
    rolling counters advance by the shipped and ordered units of this buy — the miss
    is recorded against the vendor even though the units will never arrive."

    Design: Difficulty/non_linear_state_machine/purchase_order_close_short_reopen_cycle
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line, po = \
        _short_buy_with_confirmed_line()

    po_now = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_now["po_status"] == "CLOSED_SHORT"
    assert po_now["quantity_shipped"] == 0
    assert po_now["fill_rate_pct"] == 0.0000, (
        f"shipped 0 over ordered 10 freezes at 0.0000, got {po_now['fill_rate_pct']}")
    assert po_now["closed_at"] is not None

    vendor_now = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    assert vendor_now["rolling_fill_rate_units_ordered"] >= 10, (
        "the missed buy's ordered units advance the vendor's rolling denominator")
    assert vendor_now["rolling_fill_rate_units_shipped"] == 0


def test_reopen_returns_the_buy_to_a_non_terminal_state_without_reversing_the_vendor(
        api, merchandiser_headers):
    """PRD §3.6: "Reopening moves the buy back to `ISSUED` and resets it hard:
    `quantity_ordered` is reset to the current aggregated uncovered demand for the
    buy's listings, `quantity_shipped` is reset to 0, every `POLine`'s
    `quantity_confirmed` is reset to 0, `fill_rate_pct` is cleared to null, and
    `closed_at` is cleared to null."

    PRD §3.6: "One thing is deliberately not reversed: the vendor's rolling counters
    for the previous close-short stay exactly where they were, because the miss is
    historical and reopening does not un-happen it."

    Design: Difficulty/non_linear_state_machine/purchase_order_close_short_reopen_cycle
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line, po = \
        _short_buy_with_confirmed_line()

    vendor_before = validate_success(api.get_vendor(vendor["id"], ANY), 200)

    validate_success(api.reopen_purchase_order(po["id"], PLANNER), 200)

    po_now = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_now["po_status"] == "ISSUED", (
        f"the cycle returns the buy to ISSUED, got {po_now['po_status']}")
    assert po_now["quantity_shipped"] == 0
    assert po_now["fill_rate_pct"] is None, "the realised fill rate is cleared"
    assert po_now["closed_at"] is None, "the closure instant is cleared"

    line_now = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_now["confirmation_status"] == "VENDOR_CONFIRMED", (
        "the short-shipped line reverts to VENDOR_CONFIRMED")
    assert line_now["short_shipped_units"] == 0

    vendor_after = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    assert vendor_after["rolling_fill_rate_units_ordered"] == \
        vendor_before["rolling_fill_rate_units_ordered"], (
        "the reopen does not roll back the vendor's rolling counters")
    assert vendor_after["rolling_fill_rate_units_shipped"] == \
        vendor_before["rolling_fill_rate_units_shipped"]

    order_now = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_now["order_status"] != "CANCELLED", (
        "the reopen restored a live fulfilment path")