"""Entity-surface tests: required fields, defaults, computed-field handling,
404 resolution, and pagination envelope."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId,
    create_shop_payload, create_requirement_payload,
    assert_shop,
)


def test_shop_creation_required_fields(api, admin_headers):
    """PRD §3.1: "A NetworkAdmin registers a shop by supplying its legal_name,
    the two-letter uppercase US state_code where it operates, the 5-digit
    zip_code used by locator radius queries, geocoded latitude and longitude,
    and optionally structural_capability (defaulting to false) ... The shop
    enters the network in APPLICANT posture, with lifetime_repair_count,
    pending_referral_count, and warranty_reserve_cents all zero, locator_hidden
    false at rest ... and live_compliance_score at 0.0."

    Design: Corner/entities/shop_creation_required_fields
    """
    bad = api.create_shop(
        {"state_code": "CA", "zip_code": "90001", "latitude": 34.05, "longitude": -118.24},
        admin_headers,
    )
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)

    good = api.create_shop(create_shop_payload(legal_name="Complete Body"), admin_headers)
    shop = validate_success(good, 201)
    assert_shop(shop)
    assert shop["certification_status"] == "APPLICANT"
    assert shop["lifetime_repair_count"] == 0
    assert shop["version"] == 1
    assert shop["locator_hidden"] is False


def test_shop_default_structural_capability_false(api, admin_headers):
    """PRD §3.1: "optionally structural_capability (defaulting to false)
    declaring whether the shop performs frame and unibody work."

    Design: Corner/entities/shop_default_structural_capability_false
    """
    payload = create_shop_payload(legal_name="Default Body")
    assert "structural_capability" not in payload
    shop = validate_success(api.create_shop(payload, admin_headers), 201)
    assert shop["structural_capability"] is False


def test_shop_default_structural_capability_false_when_explicit_none_omitted(api, admin_headers):
    """PRD §3.1: "optionally structural_capability (defaulting to false)". A
    second read of the same default rule: creation without the field persists
    false, and the value survives a re-fetch.

    Design: Corner/entities/shop_default_structural_capability_false
    """
    shop = validate_success(api.create_shop(create_shop_payload(), admin_headers), 201)
    refetched = validate_success(api.get_shop(shop["id"], admin_headers))
    assert refetched["structural_capability"] is False


def test_entity_not_found_returns_404(api, admin_headers):
    """PRD §2.10: "A miss anywhere in the chain ... is rejected with
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_shop(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_requirement_not_found_returns_404(api, admin_headers):
    """PRD §2.10: "A miss anywhere in the chain, or an unresolvable foreign
    key in the request body ..., is rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_requirement(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_shop_list_pagination_envelope(api, admin_headers):
    """PRD §2.3: "Paginated list responses carry limit, offset, total_count,
    and has_more in the meta object of the envelope." PRD §2.3: "limit
    controls the maximum number of items returned; it defaults to 10, with a
    minimum of 1 and a maximum of 100."

    Design: Corner/entities/shop_list_pagination_envelope
    """
    for i in range(3):
        validate_success(api.create_shop(create_shop_payload(legal_name=f"P{i}"), admin_headers), 201)
    resp = api.list_shops(admin_headers, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_shop_list_pagination_second_page(api, admin_headers):
    """PRD §2.3: "offset controls how many items are skipped; it defaults to
    0." and "Paginated list responses carry limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/shop_list_pagination_envelope
    """
    for i in range(3):
        validate_success(api.create_shop(create_shop_payload(legal_name=f"Q{i}"), admin_headers), 201)
    data, meta = validate_paginated(api.list_shops(admin_headers, params={"limit": 2, "offset": 2}))
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_computed_field_input_ignored(api, admin_headers):
    """PRD §2.6: "A Shop's certification_status is posture-driven: it is
    derived from the shop's certification-cycle and audit state, and the only
    legal writers are the transitions enumerated in §3 — no endpoint accepts a
    free-form posture value." PRD §3.1: "locator_hidden false at rest ... and
    live_compliance_score at 0.0."

    Design: Corner/entities/computed_field_input_ignored
    """
    payload = create_shop_payload(legal_name="Sneaky Body")
    payload["live_compliance_score"] = 999.0
    payload["locator_hidden"] = True
    shop = validate_success(api.create_shop(payload, admin_headers), 201)
    assert shop["locator_hidden"] is False
    assert shop["live_compliance_score"] == 0.0


def test_computed_field_certification_status_input_ignored(api, admin_headers):
    """PRD §2.6: "no endpoint accepts a free-form posture value." A create
    payload carrying a bogus posture must not affect the derived status.

    Design: Corner/entities/computed_field_input_ignored
    """
    payload = create_shop_payload(legal_name="Sneaky Posture Body")
    payload["certification_status"] = "CERTIFIED"
    shop = validate_success(api.create_shop(payload, admin_headers), 201)
    assert shop["certification_status"] == "APPLICANT"
