"""Event and listing creation shape rules, plus read round-trips and a 404."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data, validate_error,
    validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]


def _vendor_shop_event(ship_time_quote_days=14):
    """Vendor + shop + DRAFT event on 2026-09-01..2026-09-02."""
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"}, MERCH))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"}, MERCH))
    event = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Fall Outerwear Daily",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": ship_time_quote_days}, MERCH))
    return vendor, shop, event


def test_a_listing_read_returns_every_merchandising_field_unchanged(
        api, merchandiser_headers):
    """PRD §3.2: "A `Merchandiser` creates a listing with an `event_id`, a
    `vendor_sku`, a `unit_price_cents`, a `vendor_unit_cost_cents`, an
    `allocation_units`, and a `reveal_at`."

    Design: Corner/entities/listing_get_returns_the_stored_slot_unchanged
    """
    vendor, shop, event = _vendor_shop_event()
    listing = get_success_data(api_client.create_listing({
        "event_id": event["id"], "vendor_sku": "NW-RT-1",
        "unit_price_cents": 1250, "vendor_unit_cost_cents": 700,
        "allocation_units": 8, "reveal_at": "2026-09-01T06:00:00Z"}, MERCH))

    first = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert first["vendor_sku"] == "NW-RT-1"
    assert first["unit_price_cents"] == 1250
    assert first["vendor_unit_cost_cents"] == 700
    assert first["allocation_units"] == 8
    assert first["units_ordered"] == 0
    assert first["oversell_units"] == 0
    assert first["reveal_at"] == "2026-09-01T06:00:00.000Z"
    assert first["listing_status"] == "DRAFT"

    second = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert second == first, "a repeated read returns identical field values"


def test_an_unallocated_event_id_yields_the_entity_specific_not_found(api, any_headers):
    """PRD §2.5: "The catalogue for unresolvable identifiers is per entity:
    `ERR_VENDOR_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_CONFIRMATION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_POLINE_NOT_FOUND`,
    `ERR_VENDOR_SHIPMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, and `ERR_RETURN_NOT_FOUND`,
    each returned with a not-found status."

    Design: Corner/entities/event_get_with_an_unknown_id_returns_event_not_found
    """
    api.set_clock("2026-09-01T00:00:00Z", TEST_USERS["merchandiser_headers"])
    response = api.get_event("00000000-0000-4000-8000-000000000000", any_headers)
    validate_error(response, "ERR_EVENT_NOT_FOUND", expected_status=404)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}, (
        "the error payload carries exactly error_id and message")


def test_omitting_allocation_units_is_a_shape_failure(api, merchandiser_headers):
    """PRD §2.12: "then request-shape validation — which yields `ERR_INVALID_REQUEST`
    for a missing required field, a mismatched type, an undeclared enum member".

    Design: Corner/entities/listing_create_missing_allocation_units_returns_invalid_request
    """
    vendor, shop, event = _vendor_shop_event()
    response = api.create_listing({
        "event_id": event["id"], "vendor_sku": "NW-REQ-1",
        "unit_price_cents": 100, "vendor_unit_cost_cents": 60,
        "reveal_at": "2026-09-01T00:00:00Z"}, merchandiser_headers)
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    rows = validate_success(api.list_listings(ANY, {"event_id": event["id"]}), 200)
    assert rows == [], "no listing was persisted"


def test_omitting_the_ship_time_quote_is_a_shape_failure(api, merchandiser_headers):
    """PRD §3.1: "A `Merchandiser` opens an event in `DRAFT` state by supplying a
    `shop_id`, an `event_title`, a `starts_at`, an `ends_at`, and a
    `ship_time_quote_days`. The last of these is the extended ship-time expectation
    the platform will disclose to every buyer of a line in this event, and it is
    fixed at creation."

    Design: Corner/entities/event_create_omitting_ship_time_quote_returns_invalid_request
    """
    vendor, shop, event = _vendor_shop_event()
    response = api.create_event({
        "shop_id": shop["id"], "event_title": "No Quote Event",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z"},
        merchandiser_headers)
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    rows = validate_success(api.list_events(ANY, {"shop_id": shop["id"]}), 200)
    assert len(rows) == 1, "only the pre-existing event remains"

    shop_now = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_now["shop_status"] == "DRAFT"


def test_an_undeclared_ship_time_quote_bucket_is_a_shape_failure(
        api, merchandiser_headers):
    """PRD §3.1: "The quoted ship time must be one of exactly 10, 14, 21, or 30 days."

    Design: Corner/entities/event_create_with_an_out_of_enum_ship_time_quote_returns_invalid_request
    """
    vendor, shop, event = _vendor_shop_event()
    response = api.create_event({
        "shop_id": shop["id"], "event_title": "Bad Quote Event",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": 7}, merchandiser_headers)
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    accepted = validate_success(api.create_event({
        "shop_id": shop["id"], "event_title": "Good Quote Event",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": 30}, merchandiser_headers), 201)
    assert accepted["ship_time_quote_days"] == 30, (
        "30 is one of the four disclosed buckets and is admitted")

    rows = validate_success(api.list_events(ANY, {"shop_id": shop["id"]}), 200)
    assert len(rows) == 2, "the refused attempt left no row"


def test_an_event_window_must_end_strictly_after_it_starts(
        api, merchandiser_headers):
    """PRD §3.1: "The window itself is constrained. `ends_at` must fall strictly
    after `starts_at`, and the span between them may not exceed 72 hours."

    Design: Corner/endpoints/event_create_with_an_end_before_start_returns_invalid_request
    """
    vendor, shop, event = _vendor_shop_event()

    inverted = api.create_event({
        "shop_id": shop["id"], "event_title": "Inverted Window",
        "starts_at": "2026-09-02T00:00:00Z", "ends_at": "2026-09-01T00:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers)
    validate_error(inverted, "ERR_INVALID_REQUEST", expected_status=400)

    too_long = api.create_event({
        "shop_id": shop["id"], "event_title": "Overlong Window",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-04T01:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers)
    validate_error(too_long, "ERR_INVALID_REQUEST", expected_status=400)

    exact = validate_success(api.create_event({
        "shop_id": shop["id"], "event_title": "Three Day Window",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-04T00:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers), 201)
    assert exact["ends_at"] == "2026-09-04T00:00:00.000Z", (
        "a window of exactly 72 hours is inside the ceiling")

    rows = validate_success(api.list_events(ANY, {"shop_id": shop["id"]}), 200)
    assert len(rows) == 2, "two attempts were refused and left no row"