"""Numeric and bucket boundaries, each tested at the value and one step off it."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, setup_vendor_standing,
    validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
DOCK = TEST_USERS["cross_dock_headers"]

AT_BOUNDARY = "2026-09-15T00:00:00Z"   # exactly due_at for a buy issued on 09-01


def _bulk_buy_already_shipped(quantity_ordered=2000, already_shipped=1600,
                              unit_price_cents=100, confirm_units=2000):
    """A 2000-unit buy issued on 2026-09-01 with 1600 units already reported.

    Returns (vendor, event, listing, po).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=60,
        allocation_units=quantity_ordered, ship_time_quote_days=14,
        vendor_sku="NW-BULK-1", event_ends="2026-09-03T00:00:00Z")

    # The PRD's worked example snapshots a floor of 0.8500, which is the floor a
    # GOOD standing evaluation writes — so the vendor is re-scored first and the
    # buy below snapshots that 0.8500 rather than the EXCELLENT default 0.9000.
    setup_vendor_standing(vendor, shop, event, listing, target="GOOD",
                          probe_quantity=100)
    vendor = fresh_vendor(vendor["id"])

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
        line["id"], {"confirm_units": confirm_units}, vendor_h))
    get_success_data(api_client.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": already_shipped,
        "carrier_tracking_code": "BULK-TRK-1",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": already_shipped}]},
        vendor_h))
    return vendor, event, listing, po, customer


def test_a_shipment_one_unit_short_of_the_ramped_floor_is_refused(
        api, merchandiser_headers):
    """PRD §3.4: "Both the effective floor and the projected rate are rounded half up
    to four decimal places before they are compared, and the comparison is inclusive:
    a projected rate exactly equal to the effective floor is admitted, while one
    ten-thousandth of a percent below it is refused with
    `ERR_FILL_RATE_BELOW_FLOOR`. Concretely, a buy whose snapshotted floor is 0.8500
    with 2000 units ordered has an effective floor of exactly 0.8500 once 14 days have
    elapsed; a shipment taking cumulative shipped units from 1600 to 1699 yields a
    projected 0.8495 and is refused".

    Design: Difficulty/boundary_precision_check/ramped_fill_rate_floor_inclusive_at_the_boundary
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, po, customer = _bulk_buy_already_shipped()

    api.set_clock(AT_BOUNDARY, merchandiser_headers)
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    res = api.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 99,
        "carrier_tracking_code": "BULK-TRK-2",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 99}]},
        vendor_h)
    validate_error(res, "ERR_FILL_RATE_BELOW_FLOOR", expected_status=409)


def test_a_shipment_exactly_at_the_ramped_floor_is_admitted(
        api, merchandiser_headers):
    """PRD §3.4: "one taking it to 1700 yields exactly 0.8500 and is admitted".

    Design: Difficulty/boundary_precision_check/ramped_fill_rate_floor_inclusive_at_the_boundary
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, po, customer = _bulk_buy_already_shipped()

    api.set_clock(AT_BOUNDARY, merchandiser_headers)
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    validate_success(api.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 100,
        "carrier_tracking_code": "BULK-TRK-3",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 100}]},
        vendor_h), 201)

    po_now = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_now["quantity_shipped"] == 1700, (
        f"1600 plus 100 is 1700, got {po_now['quantity_shipped']}")
    assert po_now["fill_rate_pct"] == 0.8500, (
        f"1700 over 2000 rounds to 0.8500, got {po_now['fill_rate_pct']}")
    assert po_now["po_status"] == "PARTIALLY_FILLED", (
        "the buy is not yet filled, so the partial posture holds")


def _bucket_shipment_setup(quantity_ordered=300, unit_price_cents=100,
                           allocation_units=300):
    """A 300-unit buy fully confirmed, carrying six reported shipments.

    Returns (vendor, event, listing, po, shipment_ids).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=60,
        allocation_units=allocation_units, ship_time_quote_days=14,
        vendor_sku="NW-BKT-1", event_ends="2026-09-03T00:00:00Z")

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

    shipment_ids = []
    for units in (40, 40, 40, 40, 60, 60):
        ship = get_success_data(api_client.create_shipment({
            "purchase_order_id": po["id"], "quantity_shipped": units,
            "carrier_tracking_code": f"BKT-{units}-{len(shipment_ids)}",
            "shipped_at": "2026-09-01T00:00:00Z",
            "allocations": [{"listing_id": listing["id"], "quantity": units}]},
            vendor_h))
        shipment_ids.append(ship["id"])
    return vendor, event, listing, po, shipment_ids


def test_the_late_receive_into_a_bucket_at_capacity_is_refused(
        api, merchandiser_headers):
    """PRD §3.5: "The occupied units of a bucket are the summed `quantity_shipped`
    of every shipment already in `RECEIVED` whose `arrived_at` falls inside it, and
    the receive is admitted only when the occupied units plus this shipment's
    `quantity_shipped` do not exceed 100."

    Design: Difficulty/boundary_precision_check/cross_dock_zero_count_bucket_boundary_is_exclusive
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, po, ships = _bucket_shipment_setup()

    # 01:00 and 05:59:59 land in the 00:00 bucket; 06:00:00 opens a new bucket.
    validate_success(api.receive_shipment(
        ships[0], {"arrived_at": "2026-09-02T01:00:00Z",
                   "bucket_units_reported": 40}, DOCK), 200)
    validate_success(api.receive_shipment(
        ships[1], {"arrived_at": "2026-09-02T05:59:59Z",
                   "bucket_units_reported": 40}, DOCK), 200)
    validate_success(api.receive_shipment(
        ships[2], {"arrived_at": "2026-09-02T06:00:00Z",
                   "bucket_units_reported": 40}, DOCK), 200)
    validate_success(api.receive_shipment(
        ships[3], {"arrived_at": "2026-09-02T06:00:00Z",
                   "bucket_units_reported": 60}, DOCK), 200)

    res = api.receive_shipment(
        ships[4], {"arrived_at": "2026-09-02T02:00:00Z",
                   "bucket_units_reported": 40}, DOCK)
    validate_error(res, "ERR_DOCK_BUCKET_CAPACITY_EXCEEDED", expected_status=409)


def test_the_last_receive_filling_a_bucket_to_exactly_its_capacity_is_admitted(
        api, merchandiser_headers):
    """PRD §3.5: "Those buckets are aligned to 00:00 UTC and are inclusive on the
    left, exclusive on the right: a shipment arriving at exactly 06:00:00Z belongs to
    the bucket that opens at 06:00, not the one that closes there."

    Design: Difficulty/boundary_precision_check/cross_dock_zero_count_bucket_boundary_is_exclusive
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, po, ships = _bucket_shipment_setup()

    received = []
    received.append(validate_success(api.receive_shipment(
        ships[0], {"arrived_at": "2026-09-02T01:00:00Z",
                   "bucket_units_reported": 40}, DOCK), 200))
    received.append(validate_success(api.receive_shipment(
        ships[1], {"arrived_at": "2026-09-02T05:59:59Z",
                   "bucket_units_reported": 40}, DOCK), 200))

    # The 06:00:00Z receive starts a brand-new bucket, which was empty.
    opening = validate_success(api.receive_shipment(
        ships[2], {"arrived_at": "2026-09-02T06:00:00Z",
                   "bucket_units_reported": 40}, DOCK), 200)
    assert opening["shipment_status"] == "RECEIVED"
    assert opening["arrived_at"] == "2026-09-02T06:00:00.000Z"

    filling = validate_success(api.receive_shipment(
        ships[3], {"arrived_at": "2026-09-02T06:00:00Z",
                   "bucket_units_reported": 60}, DOCK), 200)
    assert filling["shipment_status"] == "RECEIVED", (
        "40 plus 60 reaches exactly the 100-unit capacity, which is admitted")

    # The 12:00Z bucket was never touched.
    later = validate_success(api.receive_shipment(
        ships[5], {"arrived_at": "2026-09-02T12:00:00Z",
                   "bucket_units_reported": 60}, DOCK), 200)
    assert later["shipment_status"] == "RECEIVED", (
        "capacity is per bucket, so a full bucket never spills into the next one")