"""Optimistic concurrency on the buy-create, consolidate and return-file writes."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data,
    setup_live_event_with_listing, setup_order_delivered,
    setup_order_line_bought_confirmed, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
DOCK = TEST_USERS["cross_dock_headers"]


def test_a_second_buy_on_a_stale_vendor_version_is_refused(
        api, merchandiser_headers):
    """PRD §2.10: "Creating a buy carries `expected_vendor_version`, compared against
    the `Vendor` the buy is placed with."

    PRD §2.10: "Each carries an expected-version field that must equal the current
    `version` of the parent entity it names; a mismatch means the caller is acting on a
    view of the parent that another writer has already superseded, and the request is
    refused with `ERR_STALE_VERSION` and a precondition-failed status."

    PRD §3.4: "Creating it also increments the vendor's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/purchase_order_create_with_a_stale_vendor_version_returns_stale_version
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=150, allocation_units=10,
        ship_time_quote_days=14, vendor_sku="NW-OCC-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    observed_version = vendor["version"]
    validate_success(api.create_purchase_order({
        "vendor_id": vendor["id"], "event_id": event["id"],
        "expected_vendor_version": observed_version}, PLANNER), 201)

    stale = api.create_purchase_order({
        "vendor_id": vendor["id"], "event_id": event["id"],
        "expected_vendor_version": observed_version}, PLANNER)
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

    vendor_now = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    assert vendor_now["version"] > observed_version, (
        "the first create's own side effect advanced the vendor's version")
    assert vendor_now["standing"] == "EXCELLENT", (
        "the refusal is not a state rejection")

    rows = validate_success(
        api.list_purchase_orders(ANY, {"vendor_id": vendor["id"]}), 200)
    assert len(rows) == 1, "the stale create persisted nothing"


def test_consolidating_with_a_version_observed_before_capture_is_refused(
        api, merchandiser_headers):
    """PRD §2.10: "Consolidating an order into a parcel carries
    `expected_order_version`, compared against the `CustomerOrder`."

    PRD §3.7: "A `CrossDockOperator` consolidates an order by supplying an
    `expected_order_version`, which is compared against the order's current `version`
    and refused with `ERR_STALE_VERSION` on a mismatch."

    Design: Corner/cross_cutting_complexity_layers/order_consolidate_with_a_stale_version_returns_stale_version
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing, customer, order, line, po = \
        setup_order_line_bought_confirmed(
            confirm_units=2, quantity=2, unit_price_cents=400,
            vendor_unit_cost_cents=200, allocation_units=5, vendor_sku="NW-OC-2")

    shipment = get_success_data(api_client.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 2,
        "carrier_tracking_code": "OC-TRK-1",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 2}]},
        {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
         "Content-Type": "application/json"}))
    get_success_data(api_client.receive_shipment(
        shipment["id"], {"arrived_at": "2026-09-01T09:00:00Z",
                         "bucket_units_reported": 2}, DOCK))

    stale_version = validate_success(api.get_order(order["id"], ANY), 200)["version"]

    get_success_data(api_client.capture_order(order["id"], PLANNER))

    res = api.consolidate_order(
        order["id"], {"expected_order_version": stale_version}, DOCK)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "AWAITING_VENDOR", (
        "the refusal left the order where it was")
    assert order_after["version"] > stale_version, (
        "the capture step is what made the observed version stale")

    parcels = validate_success(api.list_order_parcels(order["id"], ANY), 200)
    assert parcels == [], "no parcel was created by the refused consolidation"


def test_filing_a_return_on_a_stale_confirmation_version_is_refused(
        api, merchandiser_headers):
    """PRD §2.10: "Filing a return carries `expected_confirmation_version`, compared
    against the `Confirmation` the return is filed on, because the line may have been
    short-shipped or re-priced since the client last read it".

    Design: Corner/cross_cutting_complexity_layers/return_request_create_with_a_stale_confirmation_version_returns_stale_version
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    ctx = setup_order_delivered(quantity=1, unit_price_cents=800,
                                vendor_unit_cost_cents=400, allocation_units=5,
                                vendor_sku="NW-ROC-1")
    line = validate_success(api.get_confirmation(ctx["line"]["id"], ANY), 200)
    cust_h = {"X-User-ID": ctx["customer"]["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}

    first = validate_success(api.create_return({
        "confirmation_id": line["id"], "reason_code": "DAMAGED",
        "expected_confirmation_version": line["version"]}, cust_h), 201)
    assert first["return_status"] == "REQUESTED"

    after_first = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert after_first["version"] > line["version"], (
        "filing a return increments the confirmation's version")

    stale = api.create_return({
        "confirmation_id": line["id"], "reason_code": "NOT_AS_DESCRIBED",
        "expected_confirmation_version": line["version"]}, cust_h)
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

    returns = validate_success(api.list_confirmation_returns(line["id"], ANY), 200)
    assert len(returns) == 1, "only the first, fresh request was persisted"

    customer_now = validate_success(api.get_customer(ctx["customer"]["id"], ANY), 200)
    assert customer_now["refund_balance_cents"] == 0
    assert customer_now["store_credit_balance_cents"] == 0