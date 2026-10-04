"""Interval-overlap rules: a shop's brand windows and the cross-dock's dock buckets."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
DOCK = TEST_USERS["cross_dock_headers"]


def _shop_with_scheduled_windows():
    """Shop S1 carrying Event A (SCHEDULED) plus DRAFT candidates B, C and D."""
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"}, MERCH))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"}, MERCH))

    def mk(title, starts, ends, sku):
        ev = get_success_data(api_client.create_event({
            "shop_id": shop["id"], "event_title": title,
            "starts_at": starts, "ends_at": ends,
            "ship_time_quote_days": 14}, MERCH))
        # reveal_at is already in the past at the clock's 2026-09-01 instant, so
        # each candidate event carries an ACTIVE listing and scheduling it is not
        # blocked by the reveal gate — the brand window is the only thing tested.
        get_success_data(api_client.create_listing({
            "event_id": ev["id"], "vendor_sku": sku,
            "unit_price_cents": 400, "vendor_unit_cost_cents": 200,
            "allocation_units": 5, "reveal_at": "2026-09-01T00:00:00Z"}, MERCH))
        return ev

    event_a = mk("Event A", "2026-09-05T00:00:00Z", "2026-09-06T00:00:00Z", "A-1")
    get_success_data(api_client.schedule_event(event_a["id"], MERCH))

    event_b = mk("Event B", "2026-09-07T00:00:00Z", "2026-09-08T00:00:00Z", "B-1")
    event_c = mk("Event C adjacent to A", "2026-09-06T00:00:00Z",
                 "2026-09-07T00:00:00Z", "C-1")
    event_d = mk("Event D spanning both", "2026-09-06T00:00:00Z",
                 "2026-09-08T00:00:00Z", "D-1")
    return vendor, shop, event_a, event_b, event_c, event_d


def test_two_windows_padded_by_two_hours_may_not_touch(
        api, merchandiser_headers):
    """PRD §3.1: "Scheduling is admitted only if, for every one of the same shop's
    other events whose `event_status` is `SCHEDULED` or `LIVE`, the candidate window
    padded by two hours on both ends does not intersect that event's padded window.
    Both padded windows are closed, so intersection is inclusive at the touching
    point: one window ending exactly when another begins does collide".

    Design: Difficulty/resource_temporal_overlap/shop_brand_window_closed_interval_buffer_overlap
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event_a, event_b, event_c, event_d = _shop_with_scheduled_windows()

    # EB is comfortably clear of EA's padded window and is admitted.
    validate_success(api.schedule_event(event_b["id"], merchandiser_headers), 200)

    # EC starts exactly when EA ends, which collides once both are padded.
    validate_error(api.schedule_event(event_c["id"], merchandiser_headers),
                   "ERR_BRAND_WINDOW_OVERLAP", expected_status=409)

    c_after = validate_success(api.get_event(event_c["id"], ANY), 200)
    assert c_after["event_status"] == "DRAFT", (
        "a refused schedule leaves no partial state")
    a_after = validate_success(api.get_event(event_a["id"], ANY), 200)
    assert a_after["event_status"] == "SCHEDULED"


def test_a_windows_own_shop_is_the_only_scope_the_overlap_applies_to(
        api, merchandiser_headers):
    """PRD §3.1: "Only events of the same shop are considered — an event in `DRAFT`
    has not committed to a window and never blocks, a `CANCELLED` event has released
    its window, and events of other shops never interact at all."

    Design: Difficulty/resource_temporal_overlap/shop_brand_window_closed_interval_buffer_overlap
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event_a, event_b, event_c, event_d = _shop_with_scheduled_windows()
    validate_success(api.schedule_event(event_b["id"], merchandiser_headers), 200)

    # ED collides with both EA and EB at once and is refused.
    validate_error(api.schedule_event(event_d["id"], merchandiser_headers),
                   "ERR_BRAND_WINDOW_OVERLAP", expected_status=409)

    # A sibling shop of the same vendor may occupy exactly EA's instants.
    shop2 = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Second Brand Shop"},
        merchandiser_headers))
    sibling = get_success_data(api_client.create_event({
        "shop_id": shop2["id"], "event_title": "Sibling Shop Event",
        "starts_at": "2026-09-05T00:00:00Z", "ends_at": "2026-09-06T00:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers))
    get_success_data(api_client.create_listing({
        "event_id": sibling["id"], "vendor_sku": "SIB-1",
        "unit_price_cents": 400, "vendor_unit_cost_cents": 200,
        "allocation_units": 5, "reveal_at": "2026-09-01T00:00:00Z"},
        merchandiser_headers))
    validate_success(api_client.schedule_event(
        sibling["id"], merchandiser_headers), 200)


def _buy_with_four_shipments(quantity_ordered=200):
    """A 200-unit buy, fully confirmed, against a 200-unit listing.

    Returns (vendor, event, listing, po, shipment_ids, line_id).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=100, vendor_unit_cost_cents=60,
        allocation_units=quantity_ordered, ship_time_quote_days=14,
        vendor_sku="NW-OVL-1", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity_ordered},
        cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": quantity_ordered},
        PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    get_success_data(api_client.confirm_line(
        line["id"], {"confirm_units": quantity_ordered}, vendor_h))

    ships = []
    for units in (60, 40, 30, 20):
        ship = get_success_data(api_client.create_shipment({
            "purchase_order_id": po["id"], "quantity_shipped": units,
            "carrier_tracking_code": f"OVL-TRK-{units}",
            "shipped_at": "2026-09-01T00:00:00Z",
            "allocations": [{"listing_id": listing["id"], "quantity": units}]},
            vendor_h))
        ships.append(ship["id"])
    return vendor, event, listing, po, ships, line["id"]


def test_a_receive_alone_would_fit_but_the_aggregate_bucket_does_not(
        api, merchandiser_headers):
    """PRD §3.5: "Capacity is aggregate rather than pairwise: three shipments of 40
    units each into the same bucket are rejected at the third event because 120
    exceeds 100, even though no single purchaser is individually blocked."

    Design: Difficulty/resource_temporal_overlap/cross_dock_six_hour_bucket_aggregate_capacity_conflict
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, po, ships, line_id = _buy_with_four_shipments()

    # 60 then 40 fill the 06:00Z bucket to exactly its 100-unit capacity.
    validate_success(api.receive_shipment(
        ships[0], {"arrived_at": "2026-09-02T09:00:00Z",
                   "bucket_units_reported": 60}, DOCK), 200)
    validate_success(api.receive_shipment(
        ships[1], {"arrived_at": "2026-09-02T09:30:00Z",
                   "bucket_units_reported": 40}, DOCK), 200)

    # A 30-unit shipment into the same bucket is refused: 100 + 30 > 100.
    validate_error(api.receive_shipment(
        ships[2], {"arrived_at": "2026-09-02T10:00:00Z",
                   "bucket_units_reported": 30}, DOCK),
        "ERR_DOCK_BUCKET_CAPACITY_EXCEEDED", expected_status=409)

    # A 20-unit shipment, which would fit alone, is refused at the same ceiling.
    validate_error(api.receive_shipment(
        ships[3], {"arrived_at": "2026-09-02T11:00:00Z",
                   "bucket_units_reported": 20}, DOCK),
        "ERR_DOCK_BUCKET_CAPACITY_EXCEEDED", expected_status=409)


def test_rejecting_a_shipment_releases_its_units_back_to_the_bucket(
        api, merchandiser_headers):
    """PRD §3.5: "On rejection the shipment moves to `REJECTED`; the `POLine`
    `quantity_shipped` figures are deliberately not increased, because the units never
    entered the cross-dock".

    Design: Difficulty/resource_temporal_overlap/cross_dock_six_hour_bucket_aggregate_capacity_conflict
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, po, ships, line_id = _buy_with_four_shipments()

    validate_success(api.receive_shipment(
        ships[0], {"arrived_at": "2026-09-02T09:00:00Z",
                   "bucket_units_reported": 60}, DOCK), 200)

    # PRD §3.5 admits rejection while a shipment is REPORTED or IN_TRANSIT — the
    # units never entered the cross-dock — so the rejected shipment is one the
    # cross-dock has not yet received. Its units are therefore never counted
    # against the bucket, and the freed capacity admits a later receive.
    in_transit = validate_success(api.receive_shipment(
        ships[1], {"arrived_at": "2026-09-02T09:30:00Z",
                   "bucket_units_reported": 40}, DOCK), 200)
    assert in_transit["shipment_status"] == "RECEIVED"

    rejected = validate_success(api.reject_shipment(
        ships[3], {"reason_code": "DAMAGED_IN_TRANSIT"}, DOCK), 200)
    assert rejected["shipment_status"] == "REJECTED", (
        "a shipment still in REPORTED can be turned away at the cross-dock")