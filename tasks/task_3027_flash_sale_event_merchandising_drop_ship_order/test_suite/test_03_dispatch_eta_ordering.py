"""The parcel dispatch estimate and its pinned evaluation order."""

from test_helpers import (
    ANY, TEST_USERS, api_client, fresh_vendor, get_success_data,
    setup_vendor_shop_event,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
DOCK = TEST_USERS["cross_dock_headers"]

WINDOW = ("2026-08-29T00:00:00Z", "2026-08-31T00:00:00Z")
PARCEL_SEAL_AT = "2026-08-30T18:00:00Z"


def _two_speed_parcel(seal_at=PARCEL_SEAL_AT):
    """One parcel carrying a 21-day-quote line and a 5-day-quote line.

    The two lines come from two events of two shops under the same vendor, so neither
    interferes with the other's brand window.

    Returns (vendor, order, parcel, line_slow, line_fast, ship_slow, ship_fast).
    """
    api_client.set_clock("2026-08-29T00:00:00Z", MERCH)

    vendor, shop_slow, event_slow = setup_vendor_shop_event(
        ship_time_quote_days=21, event_starts=WINDOW[0], event_ends=WINDOW[1],
        event_title="Slow Event", shop_name="Northwind Brand Shop")
    shop_fast = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Second Brand Shop"}, MERCH))
    event_fast = get_success_data(api_client.create_event({
        "shop_id": shop_fast["id"], "event_title": "Fast Event",
        "starts_at": WINDOW[0], "ends_at": WINDOW[1],
        "ship_time_quote_days": 10}, MERCH))

    listing_slow = get_success_data(api_client.create_listing({
        "event_id": event_slow["id"], "vendor_sku": "SLOW-01",
        "unit_price_cents": 500, "vendor_unit_cost_cents": 300,
        "allocation_units": 5, "reveal_at": WINDOW[0]}, MERCH))
    listing_fast = get_success_data(api_client.create_listing({
        "event_id": event_fast["id"], "vendor_sku": "FAST-01",
        "unit_price_cents": 500, "vendor_unit_cost_cents": 300,
        "allocation_units": 5, "reveal_at": WINDOW[0]}, MERCH))
    for ev in (event_slow, event_fast):
        get_success_data(api_client.schedule_event(ev["id"], MERCH))
        get_success_data(api_client.launch_event(ev["id"], MERCH))

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = TEST_USERS["customer_headers"].copy()
    cust_h["X-User-ID"] = customer["id"]
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line_slow = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing_slow["id"], "quantity": 2}, cust_h))
    line_fast = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing_fast["id"], "quantity": 2}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    ships = []
    for ev, listing, line in ((event_slow, listing_slow, line_slow),
                              (event_fast, listing_fast, line_fast)):
        po = get_success_data(api_client.create_purchase_order({
            "vendor_id": vendor["id"], "event_id": ev["id"],
            "expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
        get_success_data(api_client.add_po_line(
            po["id"], {"listing_id": listing["id"], "quantity_ordered": 2}, PLANNER))
        get_success_data(api_client.issue_purchase_order(
            po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
        vendor_h = TEST_USERS["vendor_headers"].copy()
        vendor_h["X-User-ID"] = vendor["id"]
        get_success_data(api_client.confirm_line(
            line["id"], {"confirm_units": 2}, vendor_h))
        ships.append(get_success_data(api_client.create_shipment({
            "purchase_order_id": po["id"], "quantity_shipped": 2,
            "carrier_tracking_code": f"TRK-{listing['vendor_sku']}",
            "shipped_at": "2026-08-29T12:00:00Z",
            "allocations": [{"listing_id": listing["id"], "quantity": 2}]},
            vendor_h)))

    api_client.set_clock("2026-08-30T10:00:00Z", MERCH)
    for ship in ships:
        get_success_data(api_client.receive_shipment(
            ship["id"], {"arrived_at": "2026-08-30T10:00:00Z",
                         "bucket_units_reported": 2}, DOCK))
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    current = get_success_data(api_client.get_order(order["id"], ANY))
    parcel = get_success_data(api_client.consolidate_order(
        order["id"], {"expected_order_version": current["version"]}, DOCK))

    api_client.set_clock(seal_at, MERCH)
    sealed = get_success_data(api_client.seal_parcel(parcel["id"], DOCK))
    return vendor, order, sealed, line_slow, line_fast, ships[0], ships[1]


def test_dispatch_eta_adds_per_line_days_before_the_cutoff_roll(api, merchandiser_headers):
    """PRD §3.7: "Start with `sealed_at` plus the slowest contained line's event
    ship-time expectation in days, converted to hours — the slowest expectation is
    the maximum `ship_time_quote_days` across the events of the parcel's contained
    lines. Then, if the hour of `sealed_at` in UTC is at or after 17, add a whole
    additional 24 hours, because a parcel sealed after the dispatch cut-off does not
    leave the same calendar day."

    Design: Difficulty/combinatorial_formula/cross_dock_eta_pins_per_line_days_before_the_cutoff_roll
    """
    vendor, order, parcel, line_slow, line_fast, ship_slow, ship_fast = \
        _two_speed_parcel()

    assert parcel["sealed_at"] is not None
    assert parcel["dispatch_eta"] == "2026-09-21T18:00:00.000Z", (
        "sealed_at 18:00Z plus the slowest line's 21 days, rolled one further whole "
        f"day for the 17:00Z cut-off, must land on 2026-09-21T18:00:00.000Z, got "
        f"{parcel['dispatch_eta']}")


def test_dispatch_eta_is_governed_by_the_slowest_contained_line(
        api, merchandiser_headers):
    """PRD §3.7: "The alternative order — rolling the calendar day of sealing first
    and only then adding the per-line days — is explicitly not used, because the two
    orders produce different instants whenever the parcel is sealed at or after the
    cut-off hour, and the pinned order is the one that governs."

    Design: Difficulty/combinatorial_formula/cross_dock_eta_pins_per_line_days_before_the_cutoff_roll
    """
    vendor, order, parcel, line_slow, line_fast, ship_slow, ship_fast = \
        _two_speed_parcel()

    assert parcel["contained_line_ids"] is not None
    assert len(parcel["contained_line_ids"]) == 2, (
        "both events contribute one line to the parcel")
    assert parcel["vendor_shipment_count"] == 2, (
        "each event's line arrived on its own shipment")
    assert parcel["dispatch_eta"] != "2026-09-20T18:00:00Z", (
        "the rejected roll-then-add order would produce 2026-09-20T18:00:00Z")
    assert parcel["dispatch_eta"] != "2026-09-10T18:00:00.000Z", (
        "the fast event's 10-day quote must not shorten the estimate")
    assert parcel["dispatch_eta"] == "2026-09-21T18:00:00.000Z"