"""Corner tests for entity creation defaults, computed fields, not-found,
required-field, enum, and pagination claims."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_capacity_week_payload,
    create_order_line,
    create_product,
    create_sales_order_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_builder_contact_headers,
    receive_lot,
    set_clock,
    setup_builder_with_job,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.factories import create_product_payload
from test_helpers.fixtures import (
    ACCT,
    CREDIT,
    MILL,
    OPS,
    create_branch,
    create_builder,
)

NONEXISTENT_ORDER_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_product_creation_applies_defaults_and_system_fields(api):
    """PRD §3.2: "specialty_flag (default false) marking specialty-program
    products, requires_code_report (default false) which forces order
    confirmation to carry a code report reference, and requires_design_support
    (default false) marking products whose take-offs must include floor system
    design. The catalog price lever is index_premium_cents (default 0)".
    PRD §2.4: "Every persisted resource carries an id that is a server-minted
    UUID with no type prefix, a created_at timestamp, an updated_at timestamp,
    and an integer version."

    Design: Corner/entities/product_creation_applies_defaults_and_system_fields
    """
    resp = api.create_product(
        {
            "sku_code": "GLB-DF-24",
            "product_family": "GLULAM_BEAM",
            "species": "DOUGLAS_FIR",
            "dimension_label": "24in",
        },
        OPS,
    )
    data = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"
    assert data["specialty_flag"] is False
    assert data["requires_code_report"] is False
    assert data["requires_design_support"] is False
    assert data["index_premium_cents"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["created_at"].startswith("2026-09-01")
    meta = resp.json()["meta"]
    assert meta.get("api_request_id")
    assert meta.get("api_request_timestamp")


def test_inventory_lot_computed_quantities_and_received_at_on_create(api):
    """PRD §3.3: "the server stamps received_at from the logical clock, and
    that stamp drives FIFO ordering for the life of the lot. A fresh lot
    starts with qty_available_mbf equal to qty_received_mbf, both
    qty_reserved_mbf and qty_sold_mbf at 0, and lot_status ON_HAND."

    Design: Corner/entities/inventory_lot_computed_quantities_and_received_at_on_create
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    set_clock("2026-09-02T08:00:00Z")
    lot = receive_lot(branch["id"], product["id"], 12, 50000)
    assert lot["qty_available_mbf"] == 12
    assert lot["qty_reserved_mbf"] == 0
    assert lot["qty_sold_mbf"] == 0
    assert lot["lot_status"] == "ON_HAND"
    assert lot["received_at"] == "2026-09-02T08:00:00.000Z", (
        f"received_at must be stamped from the logical clock, got {lot['received_at']}"
    )
    assert lot["branch_id"] == branch["id"]
    assert lot["product_id"] == product["id"]


def test_sales_order_get_not_found_returns_404(api):
    """PRD §2.5: "each identifier in a nested URL must exist before the next
    is examined, and the first missing identifier short-circuits the request
    with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/sales_order_get_not_found_returns_404
    """
    resp = api.get_sales_order(NONEXISTENT_ORDER_ID, ACCT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"].get("api_request_id")


def test_capacity_week_missing_total_capacity_rejected(api):
    """PRD §2.5: "Malformed payloads, missing required fields, unknown enum
    members, and non-positive quantities or amounts reject with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/capacity_week_missing_total_capacity_rejected
    """
    resp = api.create_capacity_week(
        {"mill_code": "MILL-ALX", "week_start_date": "2026-09-07"}, MILL
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_invalid_family_enum_rejected(api):
    """PRD §2.9: "These spellings are exact; any other value in an enum-typed
    field is ERR_INVALID_REQUEST."

    Design: Corner/entities/product_invalid_family_enum_rejected
    """
    resp = api.create_product(
        {
            "sku_code": "PLY-CDX",
            "product_family": "PLYWOOD",
            "species": "SOUTHERN_PINE",
            "dimension_label": "4x8",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_sales_orders_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The meta object of a list response carries the pagination
    fields limit, offset, total_count, and has_more, where has_more indicates
    whether additional results exist beyond the returned window."

    Design: Corner/entities/sales_orders_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    builder, job = setup_builder_with_job(9000000)
    for qty in (1, 2, 3):
        version = get_success_data(api.get_builder(builder["id"], ACCT))["version"]
        resp = api.create_sales_order(
            job["id"],
            create_sales_order_payload(
                branch["id"],
                version,
                lines=[create_order_line(product["id"], qty_mbf=qty)],
            ),
            ACCT,
        )
        validate_success(resp, expected_status=201)

    page1, meta1 = validate_paginated(
        api.list_sales_orders(ACCT, params={"job_id": job["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_sales_orders(ACCT, params={"job_id": job["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    for order in page1 + page2:
        assert order["job_id"] == job["id"]
        assert order["order_status"] == "DRAFT"
