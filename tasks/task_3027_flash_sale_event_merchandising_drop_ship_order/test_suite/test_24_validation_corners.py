"""Validation corners: a conditional precondition, a uniqueness rule and a temporal gate."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data,
    setup_live_event_with_listing, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
CS = TEST_USERS["customer_service_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def test_a_restricted_buyer_cannot_cancel_but_an_operator_can(
        api, merchandiser_headers):
    """PRD §3.3: "requires the customer's `account_status` to be `ACTIVE` unless the
    actor is a `CustomerService` operator".

    PRD §3.8: "the operations-run checkpoint moves a customer from `ACTIVE` to
    `RESTRICTED` when the customer has accumulated three or more `CANCELLATION` ledger
    entries within the trailing 30 days."

    Design: Corner/validations/order_cancel_on_restricted_customer_requires_customer_service
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=500, vendor_unit_cost_cents=300, allocation_units=20,
        ship_time_quote_days=14, vendor_sku="NW-RST-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}

    # The order under test carries one submitted line.
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 1}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    # Three probe orders are captured and then cancelled, producing three
    # CANCELLATION ledger rows: a cancellation only books a ledger entry for the
    # amount that was actually captured (PRD §3.3).
    for i in range(3):
        probe = get_success_data(api_client.create_order(
            {"customer_id": customer["id"]}, cust_h))
        get_success_data(api_client.add_order_line(
            probe["id"], {"listing_id": listing["id"], "quantity": 1}, cust_h))
        get_success_data(api_client.submit_order(probe["id"], cust_h))
        get_success_data(api_client.capture_order(probe["id"], PLANNER))
        get_success_data(api_client.cancel_order(
            probe["id"], {"reason_code": "CHANGED_MIND"}, cust_h))

    validate_success(api.run_event_checkpoint(event["id"], merchandiser_headers), 200)

    customer_now = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert customer_now["account_status"] == "RESTRICTED", (
        "three cancellations inside 30 days restrict the account")
    ledger = validate_success(api.get_credit_ledger(customer["id"], ANY), 200)
    rows = ledger if isinstance(ledger, list) else ledger.get("data", ledger)
    assert len([r for r in rows if r["source_kind"] == "CANCELLATION"]) == 3

    validate_error(api.cancel_order(
        order["id"], {"reason_code": "CHANGED_MIND"}, cust_h),
        "ERR_INVALID_STATE", expected_status=409)

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "AWAITING_VENDOR", (
        "the buyer's own cancel is blocked by the account posture")
    assert order_after["payment_status"] == "AUTHORIZED"

    # The same cancel as an operator succeeds on the identical order.
    operator_cancelled = validate_success(api.cancel_order(
        order["id"], {"reason_code": "CHANGED_MIND"}, CS), 200)
    assert operator_cancelled["order_status"] == "CANCELLED", (
        "the account-status precondition binds the Customer actor only")


def test_a_vendor_sku_is_unique_within_its_event_but_not_across_events(
        api, merchandiser_headers):
    """PRD §3.2: "The `vendor_sku` is unique within its event, so a second listing
    carrying a code already used by another listing of the same event is refused with
    `ERR_DUPLICATE_VENDOR_SKU` — the same code may legitimately appear under a
    different event."

    Design: Corner/validations/listing_create_with_a_duplicate_vendor_sku_returns_duplicate_error
    """
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"}, MERCH))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"}, MERCH))
    event1 = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Event One",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": 14}, MERCH))
    event2 = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Event Two",
        "starts_at": "2026-09-20T00:00:00Z", "ends_at": "2026-09-21T00:00:00Z",
        "ship_time_quote_days": 14}, MERCH))

    get_success_data(api_client.create_listing({
        "event_id": event1["id"], "vendor_sku": "NW-DUP-1",
        "unit_price_cents": 100, "vendor_unit_cost_cents": 60,
        "allocation_units": 4, "reveal_at": "2026-09-01T00:00:00Z"}, MERCH))

    duplicate = api.create_listing({
        "event_id": event1["id"], "vendor_sku": "NW-DUP-1",
        "unit_price_cents": 150, "vendor_unit_cost_cents": 90,
        "allocation_units": 2, "reveal_at": "2026-09-01T00:00:00Z"}, MERCH)
    validate_error(duplicate, "ERR_DUPLICATE_VENDOR_SKU", expected_status=409)

    first_rows = validate_success(api.list_listings(ANY, {"event_id": event1["id"]}), 200)
    assert len(first_rows) == 1, "the refused row was not persisted"

    accepted = validate_success(api.create_listing({
        "event_id": event2["id"], "vendor_sku": "NW-DUP-1",
        "unit_price_cents": 150, "vendor_unit_cost_cents": 90,
        "allocation_units": 2, "reveal_at": "2026-09-20T00:00:00Z"}, MERCH), 201)
    assert accepted["vendor_sku"] == "NW-DUP-1", (
        "uniqueness is scoped per event, so the same code is accepted elsewhere")


def test_an_unrevealed_listing_blocks_submission_not_creation(
        api, merchandiser_headers):
    """PRD §2.11: "A line may not be placed against a listing whose `reveal_at` is
    still in the future — that is, the listing has not yet been revealed — and such an
    attempt is refused with `ERR_LISTING_NOT_REVEALED`."

    PRD §3.3: "Note the ordering implication: a line cannot be submitted against a
    listing that has not been revealed or against a shop that has been suspended, and
    the platform enforces both without a separate rule because the listing and shop
    gates are already part of this precondition."

    Design: Corner/validations/listing_create_with_a_future_reveal_at_is_rejected_at_submission_not_at_creation
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"}, MERCH))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"}, MERCH))
    event = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Reveal Event",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-03T00:00:00Z",
        "ship_time_quote_days": 14}, MERCH))

    # A companion listing whose reveal instant has already passed carries the
    # schedule precondition that the event needs an ACTIVE listing.
    get_success_data(api_client.create_listing({
        "event_id": event["id"], "vendor_sku": "NW-RVL-0",
        "unit_price_cents": 100, "vendor_unit_cost_cents": 60,
        "allocation_units": 4, "reveal_at": "2026-09-01T00:00:00Z"}, MERCH))
    listing = get_success_data(api_client.create_listing({
        "event_id": event["id"], "vendor_sku": "NW-RVL-1",
        "unit_price_cents": 100, "vendor_unit_cost_cents": 60,
        "allocation_units": 4, "reveal_at": "2026-09-02T12:00:00Z"}, MERCH))
    validate_success(api.schedule_event(event["id"], merchandiser_headers), 200)
    validate_success(api.launch_event(event["id"], merchandiser_headers), 200)

    listing_before = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_before["listing_status"] == "DRAFT", (
        "a listing whose reveal instant has not arrived stays DRAFT at launch")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 2}, cust_h))
    assert line["confirmation_status"] == "PENDING_AGGREGATION", (
        "the line is created successfully — the rule bites later")

    validate_error(api.submit_order(order["id"], cust_h),
                   "ERR_LISTING_NOT_REVEALED", expected_status=409)

    line_after = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_after["confirmation_status"] == "PENDING_AGGREGATION", (
        "the blocked submission left the line where it was")