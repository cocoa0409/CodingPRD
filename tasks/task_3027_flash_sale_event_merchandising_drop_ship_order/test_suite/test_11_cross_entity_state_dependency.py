"""An entity's own transition gated by a field on a different entity."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, get_success_data,
    setup_live_event_with_listing, setup_vendor_standing,
    validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def _customer_order_line(listing, quantity, email="c1@example.com", submit=False):
    """Customer + order + one line. The line is added while the shop is still open.

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
    if submit:
        get_success_data(api_client.submit_order(order["id"], cust_h))
    return customer, order, line


def _drive_standing(vendor, shop, event, listing, target, probe_quantity=480):
    """Place a probe buy whose realised fill rate lands in ``target``'s band and run
    the checkpoint, then return the vendor as re-read."""
    return setup_vendor_standing(vendor, shop, event, listing, target=target,
                                 probe_quantity=probe_quantity)


def test_an_eligible_order_cannot_submit_while_its_shop_is_suspended(
        api, merchandiser_headers):
    """PRD §3.3: "the transition to `AWAITING_VENDOR` is admitted only when the order
    has at least one line, every line's listing is `ACTIVE` and its event is `LIVE`,
    every line's shop is `OPEN`, and the logical clock is at or before the order's
    `cancellation_window_ends_at`."

    PRD §3.1: "A suspended shop's already-live events stay `LIVE` in status but stop
    accepting new lines, because ordering is gated on the shop being `OPEN`".

    Design: Difficulty/cross_entity_state_dependency/order_submission_requires_shop_open_and_event_live
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=500, vendor_unit_cost_cents=300,
        allocation_units=5, ship_time_quote_days=14, vendor_sku="NW-XE-1")
    customer, order, line = _customer_order_line(listing, 2)

    vendor_now = _drive_standing(vendor, shop, event, listing, "SUSPENDED", 480)
    assert vendor_now["standing"] == "SUSPENDED"
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
    listing_after = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_after["units_ordered"] == 0, (
        "the blocked submission consumed no allocation")


def test_a_suspended_vendor_still_suspends_every_shop_it_fronts(
        api, merchandiser_headers):
    """PRD §3.9: "A move to `SUSPENDED` suspends every shop of that vendor outright
    and, one hop further down, blocks every `SCHEDULED` event of those shops from
    launching, because the shop gate they must pass is no longer satisfied."

    PRD §3.1: "From `OPEN` or `SCHEDULED` the shop can be pushed to `SUSPENDED` by the
    system the moment the vendor's `standing` becomes `PROBATION` or `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_submission_requires_shop_open_and_event_live
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=500, vendor_unit_cost_cents=300,
        allocation_units=5, ship_time_quote_days=14, vendor_sku="NW-XE-2",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")
    customer, order, line = _customer_order_line(listing, 2)

    before = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert before["shop_status"] == "OPEN", "the live event opened the shop"

    _drive_standing(vendor, shop, event, listing, "SUSPENDED", 480)

    after = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert after["shop_status"] == "SUSPENDED", (
        "the vendor's posture drives the shop's status, never direct input")
    event_now = validate_success(api.get_event(event["id"], ANY), 200)
    assert event_now["event_status"] == "LIVE", (
        "the already-live event is not torn down, only gated")

    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    validate_error(api.submit_order(order["id"], cust_h),
                   "ERR_SHOP_SUSPENDED", expected_status=409)

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "AGGREGATING", (
        "the order is otherwise perfectly eligible but cannot leave AGGREGATING")


def test_a_probation_vendor_is_admitted_only_with_an_explicit_override(
        api, merchandiser_headers):
    """PRD §3.4: "requires the vendor's `standing` to be `EXCELLENT` or `GOOD` — or
    `PROBATION` with the caller passing `allow_probation_vendor` set to true — and
    refuses outright any vendor whose `standing` is `SUSPENDED` with
    `ERR_VENDOR_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/po_issue_requires_vendor_standing_not_suspended
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=500, vendor_unit_cost_cents=300,
        allocation_units=40, ship_time_quote_days=14, vendor_sku="NW-STD-1")
    customer, order, line = _customer_order_line(listing, 40, submit=True)

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 40}, PLANNER))

    probation_vendor = _drive_standing(vendor, shop, event, listing, "PROBATION", 400)
    assert probation_vendor["standing"] == "PROBATION"
    assert probation_vendor["fill_rate_floor_pct"] == 0.9500

    issued = validate_success(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": probation_vendor["version"],
                   "allow_probation_vendor": True}, PLANNER), 200)
    assert issued["po_status"] == "ISSUED", (
        "the explicit override admits a probation vendor")
    assert issued["fill_rate_floor_pct"] == 0.9500, (
        "the buy snapshots the vendor's own floor at issue time, got "
        f"{issued['fill_rate_floor_pct']}")


def test_a_probation_vendor_without_the_override_is_blocked_before_any_snapshot(
        api, merchandiser_headers):
    """PRD §2.6: "When `standing` is `PROBATION`, the write is refused with
    `ERR_VENDOR_STANDING_BLOCKED` unless the caller explicitly passes
    `allow_probation_vendor` set to true. Only `EXCELLENT` and `GOOD` `standing`
    proceed without a flag."

    Design: Difficulty/cross_entity_state_dependency/po_issue_requires_vendor_standing_not_suspended
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=500, vendor_unit_cost_cents=300,
        allocation_units=40, ship_time_quote_days=14, vendor_sku="NW-STD-2")
    customer, order, line = _customer_order_line(listing, 40, submit=True)

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 40}, PLANNER))

    probation_vendor = _drive_standing(vendor, shop, event, listing, "PROBATION", 400)
    assert probation_vendor["standing"] == "PROBATION"

    res = api.issue_purchase_order(
        po["id"], {"expected_vendor_version": probation_vendor["version"]}, PLANNER)
    validate_error(res, "ERR_VENDOR_STANDING_BLOCKED", expected_status=409)

    po_after = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_after["po_status"] == "DRAFT", (
        "the refusal left the buy in its initial state")
    assert po_after["fill_rate_floor_pct"] is None, (
        "the floor snapshot is taken only at ISSUED, so a refused issue records none")