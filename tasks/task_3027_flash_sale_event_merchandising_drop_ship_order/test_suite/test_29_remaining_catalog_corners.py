"""Remaining catalogue corners on the order, payout and buy-issue surface."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
CS = TEST_USERS["customer_service_headers"]
DOCK = TEST_USERS["cross_dock_headers"]


def test_an_unknown_shop_foreign_key_reports_the_shop_not_found(
        api, merchandiser_headers):
    """PRD §2.5: "foreign keys carried in a request body are checked in the order the
    endpoint declares them. Only the first failure is reported".

    PRD §2.5: "The catalogue for unresolvable identifiers is per entity:
    `ERR_VENDOR_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_CONFIRMATION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_POLINE_NOT_FOUND`,
    `ERR_VENDOR_SHIPMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, and `ERR_RETURN_NOT_FOUND`,
    each returned with a not-found status."

    Design: Corner/entities/event_create_with_an_unknown_shop_id_returns_shop_not_found
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    response = api.create_event({
        "shop_id": "00000000-0000-4000-8000-000000000009",
        "event_title": "Orphan Event",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers)
    validate_error(response, "ERR_SHOP_NOT_FOUND", expected_status=404)

    rows = validate_success(api.list_events(ANY), 200)
    assert rows == [], "the body's foreign key resolved to nothing, so nothing was created"


def test_computed_order_fields_are_not_accepted_from_the_client(
        api, merchandiser_headers):
    """PRD §3.3: "A `Customer` (or a `CustomerService` operator acting for one)
    creates an order with a `customer_id`, and it begins with `order_status`
    `AGGREGATING`, `payment_status` `AUTHORIZED`, and `order_total_cents` and
    `refund_due_cents` both 0."

    PRD §2.12: "then request-shape validation — which yields `ERR_INVALID_REQUEST` for
    a missing required field, a mismatched type, an undeclared enum member, a negative
    money value on a field the entity declares non-negative, or a `CreditLedger`
    `amount_cents` of zero."

    Design: Corner/entities/order_create_extra_field_order_total_cents_is_ignored_input
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}

    order = validate_success(api.create_order(
        {"customer_id": customer["id"], "order_total_cents": 99999,
         "order_status": "SHIPPED"}, cust_h), 201)

    assert order["order_total_cents"] == 0, (
        "the stored total is the computed value, not the supplied 99999")
    assert order["order_status"] == "AGGREGATING", (
        "the stored status is the initial value, not the supplied SHIPPED")
    assert order["payment_status"] == "AUTHORIZED"
    assert order["refund_due_cents"] == 0
    assert order["cancellation_window_ends_at"] is None, (
        "no line has been confirmed, so the window is undefined")


def test_issuing_a_buy_with_no_demand_line_is_refused(api, merchandiser_headers):
    """PRD §3.4: "The buy must carry at least one `POLine` whose `quantity_ordered` is
    greater than zero, or the issue is refused with `ERR_EMPTY_PURCHASE_ORDER`; there
    is no such thing as issuing an empty buy."

    Design: Corner/errors/empty_purchase_order_issue_and_refund_outstanding_consolidation_are_refused
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=150, allocation_units=10,
        ship_time_quote_days=14, vendor_sku="NW-BLK-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    empty = create_buy(vendor, event)
    before = validate_success(api.get_vendor(vendor["id"], ANY), 200)

    response = api.issue_purchase_order(
        empty["id"], {"expected_vendor_version": before["version"]}, PLANNER)
    validate_error(response, "ERR_EMPTY_PURCHASE_ORDER", expected_status=409)

    empty_after = validate_success(api.get_purchase_order(empty["id"], ANY), 200)
    assert empty_after["po_status"] == "DRAFT"
    assert empty_after["quantity_ordered"] == 0

    # The same vendor and event admit a buy that does carry a demand line.
    viable = create_buy(before, event)
    get_success_data(api.add_po_line(
        viable["id"], {"listing_id": listing["id"], "quantity_ordered": 4}, PLANNER))
    validate_success(api.issue_purchase_order(
        viable["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER), 200)


def test_consolidation_is_refused_while_a_refund_is_still_owed(
        api, merchandiser_headers):
    """PRD §3.6: "an order with a positive `refund_due_cents` cannot be consolidated,
    and the attempt is refused with `ERR_REFUND_OUTSTANDING`".

    PRD §3.7: "Both states additionally require the order's `payment_status` to be
    `CAPTURED` or `PARTIALLY_REFUNDED` and its `refund_due_cents` to be exactly 0 —
    which is the same outstanding-refund guard stated above, expressed as a
    precondition rather than an error at the door."

    Design: Corner/errors/empty_purchase_order_issue_and_refund_outstanding_consolidation_are_refused
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=150, allocation_units=10,
        ship_time_quote_days=14, vendor_sku="NW-OUT-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 5}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 5}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    get_success_data(api_client.confirm_line(
        line["id"], {"confirm_units": 3}, vendor_h))
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))

    owing = validate_success(api.get_order(order["id"], ANY), 200)
    assert owing["refund_due_cents"] == 600, (
        "two missing units at 300 cents each leave a positive refund owed")
    assert owing["payment_status"] == "PARTIALLY_REFUNDED"

    response = api.consolidate_order(
        order["id"], {"expected_order_version": owing["version"]}, DOCK)
    validate_error(response, "ERR_REFUND_OUTSTANDING", expected_status=409)

    parcels = validate_success(api.list_order_parcels(order["id"], ANY), 200)
    assert parcels == [], "no parcel was formed while a refund was outstanding"


def test_a_payout_larger_than_the_owed_balance_is_refused(
        api, merchandiser_headers):
    """PRD §3.6: "a cash payout may never take a customer's `refund_balance_cents`
    below zero; an attempt to pay out more than is owed is refused with
    `ERR_PAYOUT_EXCEEDS_BALANCE`."

    PRD §2.9: "All monetary fields in this system are integers denominated in cents."

    Design: Corner/errors/error_payout_exceeds_balance_on_a_payout_larger_than_owed
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=150, allocation_units=10,
        ship_time_quote_days=14, vendor_sku="NW-PAY-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 5}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 5}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    get_success_data(api_client.confirm_line(
        line["id"], {"confirm_units": 3}, vendor_h))
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))

    # A payout against a zero owed balance is refused first.
    zero_owed = api.create_payout(
        customer["id"], {"amount_cents": 1, "idempotency_key": "pay-zero-1"}, CS)
    validate_error(zero_owed, "ERR_PAYOUT_EXCEEDS_BALANCE", expected_status=409)

    # Issuing the refund moves the owed balance to 600 cents.
    validate_success(api.refund_order(
        order["id"], {"write_off_full_line": False}, PLANNER), 200)
    owing = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert owing["refund_balance_cents"] == 600

    too_much = api.create_payout(
        customer["id"], {"amount_cents": 1500, "idempotency_key": "pay-over-1"}, CS)
    validate_error(too_much, "ERR_PAYOUT_EXCEEDS_BALANCE", expected_status=409)

    unchanged = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert unchanged["refund_balance_cents"] == 600, (
        "the refused payout moved nothing")

    # A payout of exactly the balance is admitted.
    validate_success(api.create_payout(
        customer["id"], {"amount_cents": 600, "idempotency_key": "pay-exact-1"}, CS),
        201)

    settled = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert settled["refund_balance_cents"] == 0, (
        "the balance is drawn down to exactly zero, never below it")