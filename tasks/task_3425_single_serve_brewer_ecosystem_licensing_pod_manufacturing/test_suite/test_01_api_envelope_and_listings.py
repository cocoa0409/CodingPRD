"""API envelope shape, pagination, listings, and the fixed startup clock."""
from test_helpers import (
    NON_EXISTENT_UUID,
    DEFAULT_CLOCK_ISO,
    ApiErrorId,
    create_brewer_model,
    create_brand,
    create_household,
    create_variety,
    is_valid_uuid,
    register_brewer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_error_envelope_carries_meta_and_structured_data(api, admin_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.8: "the first identifier that does not resolve aborts the request
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/error_envelope_carries_meta_and_structured_data
    """
    resp = api.get_pod_variety(NON_EXISTENT_UUID, admin_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}


def test_variety_list_paginates_and_filters(api, category_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
    maximum of 100."
    PRD §3.3: "The variety listing accepts the optional filters `brand_id`,
    `status`, `roast_level`, and `material` alongside `limit` and `offset`."

    Design: Corner/entities/variety_list_paginates_and_filters
    """
    brand_a = create_brand(kind="PLATFORM_OWNED", name="Page Brand A")
    brand_b = create_brand(kind="PLATFORM_OWNED", name="Page Brand B")
    v1 = create_variety(brand_a["id"], name="V1 Light", roast_level="LIGHT")
    create_variety(brand_a["id"], name="V2 Dark", roast_level="DARK")
    create_variety(brand_b["id"], name="V3 Dark", roast_level="DARK")

    page1, meta1 = validate_paginated(
        api.list_pod_varieties(category_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_pod_varieties(category_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    by_brand, meta_b = validate_paginated(
        api.list_pod_varieties(category_headers, params={"brand_id": brand_a["id"]}))
    assert len(by_brand) == 2
    assert meta_b["total_count"] == 2
    assert all(row["brand_id"] == brand_a["id"] for row in by_brand)

    by_roast, meta_r = validate_paginated(
        api.list_pod_varieties(category_headers, params={"roast_level": "DARK"}))
    assert len(by_roast) == 2
    assert meta_r["total_count"] == 2
    assert all(row["roast_level"] == "DARK" for row in by_roast)
    assert v1["id"] not in {row["id"] for row in by_roast}


def test_variety_get_with_unknown_id_returns_not_found(api, admin_headers):
    """PRD §2.8: "Each path identifier must resolve to an existing resource
    before the next segment is examined; the first identifier that does not
    resolve aborts the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/variety_get_with_unknown_id_returns_not_found
    """
    resp = api.get_pod_variety(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_brewers_list_scopes_to_requested_household(api, support_headers):
    """PRD §3.5: "The brewers listing accepts the optional filters
    `household_id`, `model_id`, `operational`, and `warranty_status` alongside
    `limit` and `offset`."

    Design: Corner/cross_cutting_layers/brewers_list_scopes_to_requested_household
    """
    h1 = create_household(size=2, region="NW")
    h2 = create_household(size=1, region="NE")
    model = create_brewer_model(model_code="K-SCP")
    register_brewer(h1["id"], model["id"], serial_number="SN-LA6-1")
    register_brewer(h1["id"], model["id"], serial_number="SN-LA6-2")
    register_brewer(h2["id"], model["id"], serial_number="SN-LA6-3")

    rows, meta = validate_paginated(
        api.list_brewers(support_headers, params={"household_id": h1["id"]}))
    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(row["household_id"] == h1["id"] for row in rows)
    assert "SN-LA6-3" not in {row["serial_number"] for row in rows}


def test_default_logical_clock_is_fixed_startup_value(api, admin_headers):
    """PRD §2.4: "Before any call to the clock-setting capability, the logical
    clock reads exactly `2026-09-01T00:00:00Z`; this fixed startup default is
    part of the contract."

    Design: Corner/cross_cutting_layers/default_logical_clock_is_fixed_startup_value
    """
    # No clock-set call is made anywhere in this test.
    household = create_household(size=1, region="NW")
    model = create_brewer_model(model_code="K-CLK")
    brewer = register_brewer(household["id"], model["id"], serial_number="SN-LA5")

    # The registration stamp must read the fixed startup default instant.
    assert brewer["registered_at"].startswith(DEFAULT_CLOCK_ISO.rstrip("Z")), (
        f"registered_at must be the fixed startup default, got "
        f"{brewer['registered_at']}")
    assert brewer["last_brew_at"] == brewer["registered_at"]
    assert brewer["brew_count"] == 0


def test_brand_create_returns_declared_fields_and_system_fields(api, admin_headers):
    """PRD §3.1: "A `PlatformAdmin` registers a brand with a display `name`, a
    `home_region` market code, and a `kind` drawn from exactly three values"
    PRD §2.5: "`version` (integer): a system-managed integer starting at 1 on
    creation and incrementing by one on every mutation of the resource."

    Design: Corner/entities/brand_create_returns_declared_fields_and_system_fields
    """
    resp = api.create_brand(
        {"name": "Blue Mesa Coffee", "kind": "LICENSED", "home_region": "US-SW"},
        admin_headers)
    data = validate_success(resp, 201)
    assert data["name"] == "Blue Mesa Coffee"
    assert data["kind"] == "LICENSED"
    assert data["home_region"] == "US-SW"
    assert data["version"] == 1
    assert data["created_at"].startswith(DEFAULT_CLOCK_ISO.rstrip("Z"))
    assert data["updated_at"].startswith(DEFAULT_CLOCK_ISO.rstrip("Z"))
    # Server-minted id is a UUID-shaped string (PRD §2.5).
    assert is_valid_uuid(data["id"])
