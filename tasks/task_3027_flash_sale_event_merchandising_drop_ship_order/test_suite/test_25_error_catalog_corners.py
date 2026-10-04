"""Error-catalogue corners: reconciliation, a missing header, and physical bounds."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_error, validate_error_is_one_of,
    validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
CS = TEST_USERS["customer_service_headers"]
NO_HEADERS = {}


def test_derived_event_totals_are_reconciled_on_the_read(api, merchandiser_headers):
    """PRD §3.9: "A listing's `units_ordered` is recomputed as the summed `quantity`
    across its lines whose `confirmation_status` is one of `PENDING_VENDOR`,
    `VENDOR_CONFIRMED`, `PURCHASE_ORDER_ISSUED`, `IN_TRANSIT_TO_CROSS_DOCK`,
    `RECEIVED_AT_CROSS_DOCK`, `SHIPPED`, or `SHORT_SHIPPED`".

    PRD §2.12: "If a computed field on a resource being read no longer equals the
    value its calculation produces, the read repairs the field and surfaces
    `ERR_DERIVED_FIELD_DRIFT` so the discrepancy is observable rather than silent."

    Design: Corner/cross_cutting_complexity_layers/derived_event_totals_reconcile_after_a_short_ship
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=500, vendor_unit_cost_cents=300, allocation_units=3,
        ship_time_quote_days=14, vendor_sku="NW-REC-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    for email in ("c1@example.com", "c2@example.com"):
        customer = get_success_data(api_client.create_customer(
            {"email": email, "full_name": "Casey Buyer"}, ANY))
        cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
                  "Content-Type": "application/json"}
        order = get_success_data(api_client.create_order(
            {"customer_id": customer["id"]}, cust_h))
        line = get_success_data(api_client.add_order_line(
            order["id"], {"listing_id": listing["id"], "quantity": 2}, cust_h))
        get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 4}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    lines = validate_success(
        api.list_confirmations(ANY, {"listing_id": listing["id"]}), 200)
    for line in lines:
        get_success_data(api_client.confirm_line(
            line["id"], {"confirm_units": 2}, vendor_h))

    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))

    first = validate_success(api.get_event(event["id"], ANY), 200)
    assert first["units_ordered_total"] == 4, (
        "the recomputation covers the short-shipped lines exactly")
    assert first["units_po_committed_total"] == 4, (
        "a closed-short buy still counts as committed; only CANCELLED buys drop out")
    assert first["oversell_units_total"] == 1, (
        "four ordered units against an allocation of three")

    second = validate_success(api.get_event(event["id"], ANY), 200)
    assert second["units_ordered_total"] == first["units_ordered_total"]
    assert second["units_po_committed_total"] == first["units_po_committed_total"]
    assert second["oversell_units_total"] == first["oversell_units_total"]
    assert second["version"] == first["version"], (
        "the read is idempotent and repairs nothing")


def test_a_missing_user_context_header_is_reported_before_the_existence_check(
        api, merchandiser_headers):
    """PRD §2.1: "If either header is absent, or `X-User-Role` carries a value that is
    not one of the recognized role names, the request is refused with
    `ERR_MISSING_USER_CONTEXT` and a client-error status."

    PRD §2.12: "Identity is checked first: missing or malformed user context yields
    `ERR_MISSING_USER_CONTEXT`, then an unauthorized role or an unowned resource
    yields `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/errors/missing_user_context_header_returns_400_before_any_other_check
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)

    response = api.get_order("00000000-0000-4000-8000-000000000000", NO_HEADERS)
    validate_error(response, "ERR_MISSING_USER_CONTEXT", expected_status=400)

    # The same path with a valid identity does proceed to the existence check.
    with_identity = api.get_order("00000000-0000-4000-8000-000000000000", ANY)
    validate_error(with_identity, "ERR_ORDER_NOT_FOUND", expected_status=404)


def test_the_shipped_unit_ceiling_binds_on_every_later_report(
        api, merchandiser_headers):
    """PRD §3.5: "The cumulative `quantity_shipped` across all of a buy's shipments
    may never exceed that buy's `quantity_ordered`, and no line's shipped units may
    exceed its `quantity_confirmed`. Breaching either bound is refused with
    `ERR_SHIPMENT_EXCEEDS_PO`."

    Design: Corner/errors/shipment_exceeding_the_remaining_purchase_order_quantity_is_refused
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=100, vendor_unit_cost_cents=60, allocation_units=10,
        ship_time_quote_days=14, vendor_sku="NW-SC-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}

    customer = get_success_data(api_client.create_customer(
        {"email": "c9@example.com", "full_name": "Casey Nine"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 10}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    # The buy orders more than the line's ten confirmed units, so the buy never
    # fills and the shipped-unit ceiling is what binds on the later reports.
    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 100}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    get_success_data(api_client.confirm_line(
        line["id"], {"confirm_units": 10}, vendor_h))
    get_success_data(api_client.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 8,
        "carrier_tracking_code": "SC-TRK-1",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 8}]}, vendor_h))

    # A later report breaches the line's confirmed ceiling: 8 already shipped
    # plus this report would take the line past its ten confirmed units.
    over = api.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 3,
        "carrier_tracking_code": "SC-TRK-2",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 3}]}, vendor_h)
    validate_error(over, "ERR_SHIPMENT_EXCEEDS_PO", expected_status=409)

    po_now = validate_success(api.get_purchase_order(po["id"], ANY), 200)
    assert po_now["quantity_shipped"] == 8, "the refusal left the total untouched"

    # The remaining headroom to the line's confirmed quantity is exactly two units.
    validate_success(api.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 2,
        "carrier_tracking_code": "SC-TRK-3",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 2}]}, vendor_h), 201)

    # The ceiling binds on every later report, not just the first over-report:
    # the line now holds its full confirmed quantity, so nothing further is admitted.
    again = api.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 1,
        "carrier_tracking_code": "SC-TRK-4",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 1}]}, vendor_h)
    validate_error_is_one_of(again, ["ERR_SHIPMENT_EXCEEDS_PO"])


def test_a_reallocation_must_strictly_exceed_the_units_already_sold(
        api, merchandiser_headers):
    """PRD §3.2: "The reallocation must strictly increase `allocation_units` above the
    listing's current `units_ordered`; a value that does not strictly exceed the units
    already sold is refused with `ERR_ALLOCATION_EXCEEDED`".

    PRD §3.2: "On success the supplied value becomes the new `allocation_units`, a
    listing that was `SOLD_OUT` returns to `ACTIVE`, and the listing's
    `oversell_units` resets to 0".

    Design: Corner/errors/reallocation_below_or_equal_to_units_ordered_is_refused
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=200, vendor_unit_cost_cents=100, allocation_units=4,
        ship_time_quote_days=14, vendor_sku="NW-RAL-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 4}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    sold_out = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert sold_out["units_ordered"] == 4
    assert sold_out["listing_status"] == "SOLD_OUT"

    equal = api.reallocate_listing(
        listing["id"],
        {"allocation_units": 4, "expected_listing_version": sold_out["version"]},
        merchandiser_headers)
    validate_error(equal, "ERR_ALLOCATION_EXCEEDED", expected_status=409)

    still = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert still["allocation_units"] == 4
    assert still["listing_status"] == "SOLD_OUT"

    revived = validate_success(api.reallocate_listing(
        listing["id"],
        {"allocation_units": 5, "expected_listing_version": still["version"]},
        merchandiser_headers), 200)
    assert revived["allocation_units"] == 5
    assert revived["listing_status"] == "ACTIVE", (
        "raising the allocation revives a sold-out listing")
    assert revived["oversell_units"] == 0


def test_an_oversell_beyond_twenty_percent_of_the_allocation_is_refused(
        api, merchandiser_headers):
    """PRD §3.4: "A listing's oversell may not exceed 20 percent of its
    `allocation_units`; a confirmation or reallocation that would push it past that
    bound is refused with `ERR_OVERSELL_LIMIT_EXCEEDED`."

    Design: Corner/errors/oversell_limit_and_derived_drift_are_reachable
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=200, vendor_unit_cost_cents=100, allocation_units=4,
        ship_time_quote_days=14, vendor_sku="NW-OSL-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 10}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 10}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))

    before = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert before["units_ordered"] == 10
    assert before["allocation_units"] == 4

    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    over = api.confirm_line(line["id"], {"confirm_units": 10}, vendor_h)
    # The PRD names the error but does not pin which of the two guards at the
    # confirmation-boundary priority reports first: §3.4's fill-rate gate ("the
    # confirmation must leave the buy's projected fill rate at or above the
    # effective floor") compares a projected rate of 0.0000 against a positive
    # effective floor, so a faithful reader may legitimately surface either.
    validate_error_is_one_of(over, ["ERR_OVERSELL_LIMIT_EXCEEDED",
                                    "ERR_FILL_RATE_BELOW_FLOOR"])

    after = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert after["units_ordered"] == 10, (
        "the refused confirmation did not disturb the demand figure")