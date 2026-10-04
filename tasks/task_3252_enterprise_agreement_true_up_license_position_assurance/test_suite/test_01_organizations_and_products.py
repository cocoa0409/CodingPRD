"""Organizations: price-level tiering, updates, RBAC, and catalog basics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_organization,
    create_organization,
    create_organization_payload,
    create_product_payload,
    get_success_data,
    is_valid_uuid,
    update_organization_devices,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_organization_created_with_computed_price_level_a(api):
    """PRD §2.7: "the server derives a `price_level` of `A`, `B`, `C`, or `D` from it. The boundaries are inclusive on the lower side: fewer than 250 qualified devices is level `A`; at least 250 but fewer than 2400 is level `B`; at least 2400 but fewer than 6000 is level `C`; 6000 or more is level `D`."

    Design: Corner/entities/organization_creation_applies_price_level_default_and_computed
    """
    resp = api.create_organization(
        {"legal_name": "Acme Corp", "qualified_device_count": 100},
        TEST_USERS["program_admin_headers"],
    )
    data = validate_success(resp, 201)
    assert_organization(data)
    assert data["price_level"] == "A", f"100 devices must derive level A, got {data['price_level']}"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])


def test_organization_missing_qualified_device_count_returns_invalid_request(api):
    """PRD §3.1: "registering the customer organization with its `legal_name` and declared `qualified_device_count`; the count must be at least 1".
    PRD §2.9: "malformed-request rejection (`ERR_INVALID_REQUEST`, HTTP 400) as the outermost catch for missing required fields, type mismatches, out-of-set enum values, and violated numeric lower bounds."

    Design: Corner/entities/organization_missing_qualified_device_count_returns_invalid_request
    """
    resp = api.create_organization({"legal_name": "No Count Corp"}, TEST_USERS["program_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_product_invalid_enum_license_model_returns_invalid_request(api):
    """PRD §3.2: "its `license_model` of `PER_USER`, `PER_DEVICE`, or `PER_SERVER_CORE`".
    PRD §2.9: "malformed-request rejection (`ERR_INVALID_REQUEST`, HTTP 400) as the outermost catch for missing required fields, type mismatches, out-of-set enum values, and violated numeric lower bounds."

    Design: Corner/entities/product_invalid_enum_license_model_returns_invalid_request
    """
    payload = create_product_payload(
        sku="BAD1", name="Bad", license_model="PER_SOCKET",
        license_kind="SUBSCRIPTION", edition="STANDARD", family="X",
        annual_unit_price_cents=1000, license_mobility=False,
    )
    resp = api.create_product(payload, TEST_USERS["program_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_get_agreement_not_found(api):
    """PRD §2.9: "Only after auth does the server check existence: path parameters and body references are resolved left to right — organization, then agreement, then anniversary, then product, then entitlement, then deployment, then report, then line, then grant, then commitment, then authorization, then snapshot — and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_agreement_not_found
    """
    resp = api.get_agreement("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", TEST_USERS["program_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_products_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and must be at most 100. `offset` defaults to 0. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`."

    Design: Corner/entities/products_list_pagination_envelope
    """
    for i in range(1, 4):
        payload = create_product_payload(sku=f"PG{i}", name=f"P{i}")
        resp = api.create_product(payload, TEST_USERS["program_admin_headers"])
        assert resp.status_code == 201, get_success_data(resp)
    resp = api.list_products(TEST_USERS["auditor_headers"], params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert len(data) == 2


def test_price_level_tier_boundary_249_vs_250(api):
    """PRD §2.7: "The boundaries are inclusive on the lower side: fewer than 250 qualified devices is level `A`; at least 250 but fewer than 2400 is level `B`; at least 2400 but fewer than 6000 is level `C`; 6000 or more is level `D`. Every update to `qualified_device_count` — including the update endpoint that also accepts an optional new `legal_name` — recomputes `price_level` immediately and increments the organization's `version`."

    Design: Difficulty/boundary_precision_check/price_level_tier_boundary_249_vs_250
    """
    org = create_organization(legal_name="Tier Org", qualified_device_count=249)
    assert org["price_level"] == "A", f"249 devices must stay level A, got {org['price_level']}"
    updated = update_organization_devices(org["id"], 250)
    assert updated["price_level"] == "B", f"250 devices must cross into level B, got {updated['price_level']}"


def test_price_level_tier_boundary_high_tiers(api):
    """PRD §2.7: "The boundaries are inclusive on the lower side: fewer than 250 qualified devices is level `A`; at least 250 but fewer than 2400 is level `B`; at least 2400 but fewer than 6000 is level `C`; 6000 or more is level `D`."

    Design: Difficulty/boundary_precision_check/price_level_tier_boundary_249_vs_250
    """
    org = create_organization(legal_name="Tier High Org", qualified_device_count=2399)
    assert org["price_level"] == "B"
    assert update_organization_devices(org["id"], 2400)["price_level"] == "C"
    assert update_organization_devices(org["id"], 5999)["price_level"] == "C"
    assert update_organization_devices(org["id"], 6000)["price_level"] == "D"


def test_auditor_is_read_only(api):
    """PRD §2.1: "`Auditor` is strictly read-only: it may call any GET endpoint and the shortfall-assessment capability, and nothing else."
    PRD §2.1: "If the role is recognized but not permitted for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/auditor_is_read_only
    """
    payload = create_product_payload(
        sku="AU1", name="Aud", license_model="PER_USER", license_kind="SUBSCRIPTION",
        edition="STANDARD", family="F", annual_unit_price_cents=1000, license_mobility=False,
    )
    resp = api.create_product(payload, TEST_USERS["auditor_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_products(headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
