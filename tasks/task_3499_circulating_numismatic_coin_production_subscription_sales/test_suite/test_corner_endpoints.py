"""Corner coverage — response envelope shapes (PRD §2.2), the pagination
envelope and offset semantics (§2.3), and the order list's product_id filter
(§3.6)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_collector, assert_system_timestamp, validate_created
from test_helpers.constants import BOOT_CLOCK_UTC
from test_helpers.factories import create_collector_payload
from test_helpers.fixtures import (
    create_collector,
    create_product,
    place_order,
    set_clock,
)

MANAGER = TEST_USERS["program_manager_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def test_response_envelope_success_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §4: "Resource-creating operations — denominations, Federal Reserve
    orders, procurement lots, production runs, commemorative programs,
    products, collectors, numismatic orders, subscriptions, billing cycles
    (each of which creates an invoice), bullion issues, authorized purchasers,
    bullion allocations, and error-coin cases — respond 201 on success and
    return the created resource."

    Design: Corner/endpoints/response_envelope_success_shape
    """
    set_clock(api, BOOT_CLOCK_UTC)

    resp = api.create_collector(
        create_collector_payload(
            full_name="Envelope", email="env@example.com", household_id="HH-1"),
        ANONYMOUS)
    data = validate_created(resp)  # collector registration is a create: 201

    body = resp.json()
    assert body["response_type"] == "object", (
        f"single-resource create must carry response_type 'object', "
        f"got {body['response_type']!r}")
    request_id = body["meta"]["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {request_id!r}")
    assert_system_timestamp(
        body["meta"]["api_request_timestamp"], "meta.api_request_timestamp")
    assert_collector(data)
    assert data["full_name"] == "Envelope"


def test_response_envelope_error_shape(api):
    """PRD §2.7: "Path existence — every id in the URL path resolves to an
    existing resource, validated left to right along the path
    (`ERR_NOT_FOUND`, 404)."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/response_envelope_error_shape
    """
    set_clock(api, BOOT_CLOCK_UTC)

    resp = api.get_order(NON_EXISTENT_UUID, MANAGER)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)  # 404 auto-checked

    assert err["message"].strip(), "data.message must be a non-empty string"
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, "
        f"got {sorted(body['meta'].keys())}")


def test_list_pagination_envelope_and_offset(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query
    parameters."
    PRD §2.3: "`offset` defaults to 0. List responses are sorted by
    `created_at` ascending, and the `meta` object of a list response carries
    the pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_pagination_envelope_and_offset
    """
    set_clock(api, BOOT_CLOCK_UTC)
    for _ in range(3):
        # Auto-unique product_family per product, so the 24h family
        # release-gap rule never trips between these three rows.
        create_product(api)

    page1 = api.list_products(MANAGER, params={"limit": 2})
    rows1, meta1 = validate_paginated(page1)
    assert page1.json()["response_type"] == "array", (
        "a list endpoint must carry response_type 'array'")
    assert meta1["total_count"] == 3, (
        f"total_count must be 3 with three products, got {meta1['total_count']}")
    assert meta1["has_more"] is True, "page 1 of limit=2 over 3 rows must have has_more"
    assert len(rows1) == 2, f"limit=2 must return exactly 2 rows, got {len(rows1)}"
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2 = api.list_products(MANAGER, params={"limit": 2, "offset": 2})
    rows2, meta2 = validate_paginated(page2)
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False, "the final page must report has_more false"
    assert len(rows2) == 1, f"offset=2 over 3 rows must return exactly 1 row, got {len(rows2)}"
    assert meta2["offset"] == 2


def test_orders_list_filter_by_product(api):
    """PRD §3.6: "The order's `total_cents` is its `quantity` multiplied by
    the product's `price_cents`, its `payment_status` begins `UNPAID`, and the
    order list accepts optional `collector_id`, `product_id`,
    `allocation_status`, and `payment_status` filters."

    Design: Corner/endpoints/orders_list_filter_by_product
    """
    set_clock(api, BOOT_CLOCK_UTC)
    p1 = create_product(api, product_code="F-1", product_family="FA",
                        release_datetime="2026-08-15T00:00:00Z")
    p2 = create_product(api, product_code="F-2", product_family="FB",
                        release_datetime="2026-08-15T00:00:00Z")
    set_clock(api, "2026-09-01T00:05:00Z")  # sweep both products to ON_SALE
    c1 = create_collector(api, full_name="F One", email="f1@example.com",
                          household_id="HH-1")
    c2 = create_collector(api, full_name="F Two", email="f2@example.com",
                          household_id="HH-2")
    place_order(api, p1["id"], c1, 1)
    place_order(api, p2["id"], c2, 2)

    resp = api.list_orders(MANAGER, params={"product_id": p1["id"]})
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, (
        f"filtering by product_id must return exactly the p1 order, "
        f"got total_count {meta['total_count']}")
    assert len(rows) == 1
    assert rows[0]["product_id"] == p1["id"], (
        f"the single row must belong to {p1['id']}, got {rows[0]['product_id']}")
