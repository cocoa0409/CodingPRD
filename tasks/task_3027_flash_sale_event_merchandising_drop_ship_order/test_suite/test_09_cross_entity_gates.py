"""Gates that live on a different entity from the write they block."""
from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data,
    setup_live_event_with_listing, setup_vendor_standing,
    validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def _line_placed_before_suspension(listing, quantity=1, email="c1@example.com"):
    """A customer order carrying one line on a live listing, added while the shop is
    still open so the later gate is the only obstacle.

    Returns (customer, order, line).
    """
    customer = get_success_data(api_client.create_customer(
        {"email": email, "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity}, cust_h))
    return customer, order, line


def test_submitting_an_order_against_a_suspended_shop_is_refused(
        api, merchandiser_headers):
    """PRD §2.6: "Separately, the owning shop is gated: a new line against a listing
    whose shop is `SUSPENDED` or `CLOSED`, and any attempt to launch an event under
    such a shop, is refused with `ERR_SHOP_SUSPENDED`."

    PRD §3.1: "A suspended shop's already-live events stay `LIVE` in status but stop
    accepting new lines, because ordering is gated on the shop being `OPEN`".

    Design: Difficulty/priority_pair_validation_conflict/shop_standing_gate_defeats_listing_forward_invariants
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=700, vendor_unit_cost_cents=400, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-PR-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")
    customer, order, line = _line_placed_before_suspension(listing, quantity=1)

    vendor_now = setup_vendor_standing(vendor, shop, event, listing,
                                       target="SUSPENDED", probe_quantity=480)
    assert vendor_now["standing"] == "SUSPENDED", (
        f"a fully-missed buy suspends the vendor, got {vendor_now['standing']}")
    assert vendor_now["fill_rate_floor_pct"] == 1.0000
    shop_now = get_success_data(api_client.get_shop(shop["id"], ANY))
    assert shop_now["shop_status"] == "SUSPENDED", (
        "a suspended vendor suspends every one of its shops")
    event_now = get_success_data(api_client.get_event(event["id"], ANY))
    assert event_now["event_status"] == "LIVE", (
        "the already-live event keeps its status; only ordering under it stops")

    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    validate_error(api.submit_order(order["id"], cust_h),
                   "ERR_SHOP_SUSPENDED", expected_status=409)

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "AGGREGATING", (
        "nothing about the order itself is invalid, yet it did not advance")
    assert order_after["order_total_cents"] == 0
    line_after = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_after["confirmation_status"] == "PENDING_AGGREGATION", (
        "the blocked submission left the line where it was")
    listing_after = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_after["units_ordered"] == 0, (
        "the blocked submission consumed no allocation")


def test_issuing_a_buy_against_a_suspended_vendor_is_refused_without_touching_it(
        api, merchandiser_headers):
    """PRD §2.6: "A buy or a shipment report against a vendor whose `standing` is
    `SUSPENDED` is refused outright with `ERR_VENDOR_SUSPENDED`."

    PRD §2.12: "a request that names a transition the state machine does not permit is
    refused with `ERR_INVALID_STATE`, and nothing else in the request is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/shop_standing_gate_defeats_listing_forward_invariants
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=700, vendor_unit_cost_cents=400, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-PR-3",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")
    customer, order, line = _line_placed_before_suspension(listing, quantity=5,
                                                           email="c2@example.com")
    get_success_data(api.submit_order(
        order["id"], {"X-User-ID": customer["id"], "X-User-Role": "Customer",
                      "Content-Type": "application/json"}))

    suspended = setup_vendor_standing(vendor, shop, event, listing,
                                      target="SUSPENDED", probe_quantity=480)
    assert suspended["standing"] == "SUSPENDED"

    before = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    # A buy against a SUSPENDED vendor is refused outright — the vendor gate is
    # applied when the buy is placed, not only when it is issued (PRD §2.6).
    validate_error(api.create_purchase_order({
        "vendor_id": vendor["id"], "event_id": event["id"],
        "expected_vendor_version": before["version"]}, PLANNER),
        "ERR_VENDOR_SUSPENDED", expected_status=409)

    after = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    assert after["version"] == before["version"], (
        "the refused buy bumped no version")