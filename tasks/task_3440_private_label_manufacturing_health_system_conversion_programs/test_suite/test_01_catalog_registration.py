"""Catalog, facilities, response envelope, and registration lifecycle tests."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_facility,
    assert_product,
    create_facility_payload,
    create_product,
    create_product_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_regulatory_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_facility_create_returns_201(api):
    """PRD §4: "Operations that create a new stand-alone resource return `201
    Created`; operations that modify an existing resource, record events against
    it, or drive its state machine return `200 OK`, as do all reads."
    PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."

    Design: Corner/entities/facility_create_success_returns_201
    """
    resp = api.create_facility(
        create_facility_payload(
            name="Fac OK",
            health_system_name="HS OK",
            facility_type="ACUTE_CARE",
            ship_to_address="20 Vine St",
        ),
        headers=ADMIN,
    )
    data = validate_success(resp, 201)
    assert_facility(data)
    assert data["name"] == "Fac OK"
    assert data["facility_type"] == "ACUTE_CARE"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])


def test_response_envelope_success_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/response_envelope_success_shape
    """
    resp = api.create_facility(
        create_facility_payload(name="Fac ENV", facility_type="CLINIC"),
        headers=ADMIN,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith(
        "req_"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-object response must omit meta.{field}"
    assert isinstance(body["data"], dict)


def test_product_create_defaults_applied(api):
    """PRD §3.1: "The `availability` flag — `ACTIVE` or `DISCONTINUED` — governs
    orderability and defaults to `ACTIVE`."
    PRD §3.1: "`order_multiple` (orders must be a multiple of this quantity
    unless low-unit-of-measure terms apply; at least 1, defaulting to 1 when
    omitted)".
    PRD §3.1: "its system-managed `registration_status` initializes to
    `UNREGISTERED` at creation."

    Design: Corner/entities/product_create_defaults_applied
    """
    resp = api.create_product(
        create_product_payload(
            sku="DF-1", name="Plain gauze", units_per_case=1, each_price_cents=10
        ),
        headers=ADMIN,
    )
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["availability"] == "ACTIVE"
    assert data["order_multiple"] == 1
    assert data["lum_eligible"] is False
    assert data["registration_status"] == "UNREGISTERED"
    assert data["version"] == 1


def test_product_create_missing_sku_400(api):
    """PRD §2.6: "any request that is malformed on its face — a required field
    missing, a value of the wrong shape, an unknown enum member, or an
    action-specific required field absent, such as a substitution decision
    payload that omits its `request_id` — is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/product_create_missing_required_sku_returns_400
    """
    payload = create_product_payload(sku="DF-X")
    del payload["sku"]
    resp = api.create_product(payload, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_product_create_invalid_category_400(api):
    """PRD §3.1: "a `category` drawn from `SURGICAL_INSTRUMENTS`, `WOUND_CARE`,
    `EXAM_GLOVES`, `STERILIZATION_SUPPLIES`, `UROLOGICAL`, or `RESPIRATORY`".
    PRD §2.6: "any request that is malformed on its face — a required field
    missing, a value of the wrong shape, an unknown enum member, or an
    action-specific required field absent, such as a substitution decision
    payload that omits its `request_id` — is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/product_create_invalid_enum_category_rejected
    """
    resp = api.create_product(
        create_product_payload(sku="DF-2", category="PHARMA"), headers=ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_product_create_duplicate_sku_409(api):
    """PRD §3.1: "`sku` — globally unique across all products, so a colliding
    `sku` is rejected with `ERR_DUPLICATE_SKU` (HTTP 409)".

    Design: Corner/validations/duplicate_sku_rejected
    """
    first = api.create_product(create_product_payload(sku="DUP-1"), headers=ADMIN)
    validate_success(first, 201)
    resp = api.create_product(
        create_product_payload(
            sku="DUP-1",
            brand_type="PRIVATE_LABEL",
            category="UROLOGICAL",
            sterile=True,
            device_class="CLASS_II",
        ),
        headers=ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


def test_products_create_missing_auth_401(api):
    """PRD §2.1: "A request missing either header, or carrying a role name the
    system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/products_create_missing_auth_returns_401
    """
    resp = api_client.create_product(create_product_payload(sku="AU-1"), headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_registration_approve_from_unregistered_409(api):
    """PRD §3.1: "Any event attempted from a state that does not sponsor it (for
    example, `APPROVE` against an `UNREGISTERED` product, or any event against a
    `REGISTERED` one) is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/registration_approve_from_unregistered_rejected
    """
    product = create_product(sku="RG-1", brand_type="PRIVATE_LABEL")
    resp = api.record_registration_event(
        product["id"], {"event": "APPROVE"}, make_regulatory_headers("reg-1")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    # State did not move: SUBMIT (legal only from UNREGISTERED/REJECTED) succeeds.
    ok = api.record_registration_event(
        product["id"], {"event": "SUBMIT"}, make_regulatory_headers("reg-1")
    )
    assert validate_success(ok)["registration_status"] == "SUBMITTED"


def test_registration_resubmit_cycle(api):
    """PRD §3.1: "Recording a `SUBMIT` event against an `UNREGISTERED` product
    moves it to `SUBMITTED`; a product whose dossier fails review can be
    resubmitted, so `SUBMIT` also moves a `REJECTED` product back to `SUBMITTED`,
    closing the resubmission cycle."

    Design: Corner/state_machines/registration_resubmit_after_reject_cycles
    """
    product = create_product(sku="RG-2", brand_type="PRIVATE_LABEL")
    reg = make_regulatory_headers("reg-1")
    validate_success(
        api.record_registration_event(product["id"], {"event": "SUBMIT"}, reg)
    )
    rejected = validate_success(
        api.record_registration_event(product["id"], {"event": "REJECT"}, reg)
    )
    assert rejected["registration_status"] == "REJECTED"
    resubmitted = validate_success(
        api.record_registration_event(product["id"], {"event": "SUBMIT"}, reg)
    )
    assert resubmitted["registration_status"] == "SUBMITTED"
    final = validate_success(
        api.record_registration_event(product["id"], {"event": "APPROVE"}, reg)
    )
    assert final["registration_status"] == "REGISTERED"
