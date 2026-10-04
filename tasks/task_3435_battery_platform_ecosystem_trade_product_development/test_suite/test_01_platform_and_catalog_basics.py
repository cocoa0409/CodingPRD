"""Platform creation, catalog request shape, envelope, auth and role gating."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_battery_platform,
    create_platform,
    pack_payload,
    platform_payload,
    set_clock,
    tool_model_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_platform_create_returns_computed_defaults(api, platform_admin_headers):
    """PRD §3.1: "A new platform starts with `status` `ACTIVE` and
    `current_generation` 0."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by exactly 1 on every mutation of that resource"
    PRD §4: "creating a new resource answers 201"

    Design: Corner/entities/platform_create_returns_computed_defaults
    """
    set_clock()
    resp = api.create_platform(platform_payload(code="MX12", interface_key="INTERFACE_B",
                                                chemistry_family="LFP", backward_commitment_years=8,
                                                forward_commitment_generations=2),
                               platform_admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    data = body["data"]
    assert_battery_platform(data)
    assert data["status"] == "ACTIVE"
    assert data["current_generation"] == 0
    assert data["version"] == 1
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_pack_create_missing_required_sku_returns_invalid_request(api, product_engineer_headers):
    """PRD §2.8: "Request shape: required fields present, enum membership valid,
    numeric ranges respected ... otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/pack_create_missing_required_sku_returns_invalid_request
    """
    set_clock()
    pf = create_platform(code="MX18")
    payload = pack_payload(pf["id"])
    del payload["sku"]
    resp = api.create_pack(payload, product_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_tool_create_with_invalid_enum_returns_invalid_request(api, product_engineer_headers):
    """PRD §3.3: "a target `trade` of `PLUMBING`, `ELECTRICAL`, `HVAC`,
    `CARPENTRY`, `MASONRY`, or `AUTOMOTIVE`"
    PRD §2.8: "Request shape: required fields present, enum membership valid,
    numeric ranges respected ... otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/tool_create_with_invalid_enum_returns_invalid_request
    """
    set_clock()
    pf = create_platform(code="MX18")
    resp = api.create_tool_model(
        tool_model_payload(pf["id"], model_code="T-X", trade="UNDERWATER"),
        product_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_tool_create_corded_without_runtime_target_returns_invalid_request(api, product_engineer_headers):
    """PRD §3.3: "`runtime_target_min` — the runtime target in minutes, strictly
    positive when present — is REQUIRED exactly when `corded_conversion` is true
    and forbidden otherwise (`ERR_VALIDATION`)."

    Design: Corner/entities/tool_create_corded_without_runtime_target_returns_invalid_request
    """
    set_clock()
    pf = create_platform(code="MX18")
    bad = api.create_tool_model(
        tool_model_payload(pf["id"], model_code="T-C1", trade="MASONRY", category="SAW",
                           tier="TRADE_SPECIALIST", corded_conversion=True, avg_power_draw_w=900,
                           min_pack_generation=1, max_pack_generation=1),
        product_engineer_headers,
    )
    validate_error(bad, ApiErrorId.ERR_VALIDATION)
    ok = api.create_tool_model(
        tool_model_payload(pf["id"], model_code="T-C2", trade="MASONRY", category="SAW",
                           tier="TRADE_SPECIALIST", corded_conversion=False, avg_power_draw_w=900,
                           min_pack_generation=1, max_pack_generation=1),
        product_engineer_headers,
    )
    data = validate_success(ok, 201)
    assert data["stage"] == "CONCEPT"


def test_pack_create_future_generation_rejected(api, product_engineer_headers):
    """PRD §3.1: "A new pack's `pack_generation` must be at least 1 and at most
    the platform's `current_generation` plus 1 — the generation ratchet permits
    only the next generation beyond what is certified, and a violation is
    `ERR_PACK_GENERATION_VIOLATION`."

    Design: Corner/validations/pack_create_future_generation_rejected
    """
    set_clock()
    pf = create_platform(code="MX18")  # current_generation 0
    resp = api.create_pack(pack_payload(pf["id"], sku="P-SKIP", pack_generation=2),
                           product_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_PACK_GENERATION_VIOLATION)


def test_tool_create_beyond_forward_commitment_rejected(api, product_engineer_headers):
    """PRD §3.1: "A new tool's `max_pack_generation` must be at least its
    `min_pack_generation` and at most the platform's `current_generation` plus
    the platform's `forward_commitment_generations`; overshooting that ceiling
    is `ERR_FORWARD_COMMITMENT_EXCEEDED`."

    Design: Corner/validations/tool_create_beyond_forward_commitment_rejected
    """
    set_clock()
    pf = create_platform(code="MX18")  # current 0, forward 2 -> ceiling 2
    resp = api.create_tool_model(
        tool_model_payload(pf["id"], model_code="T-FWD", trade="HVAC", tier="PROFESSIONAL",
                           avg_power_draw_w=300, min_pack_generation=1, max_pack_generation=3),
        product_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORWARD_COMMITMENT_EXCEEDED)
    ok = api.create_tool_model(
        tool_model_payload(pf["id"], model_code="T-FWD-OK", trade="HVAC", tier="PROFESSIONAL",
                           avg_power_draw_w=300, min_pack_generation=1, max_pack_generation=2),
        product_engineer_headers,
    )
    validate_success(ok, 201)


def test_pack_get_with_unknown_id_returns_not_found(api, platform_admin_headers):
    """PRD §2.8: "Existence: path ids and body foreign keys ... exist, validated
    left to right; otherwise `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/pack_get_with_unknown_id_returns_not_found
    """
    set_clock()
    resp = api.get_pack(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_single_object_envelope_shape(api, platform_admin_headers, product_engineer_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/single_object_envelope_shape
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk_resp = api.create_pack(pack_payload(pf["id"], sku="P-ENV"), product_engineer_headers)
    pk = validate_success(pk_resp, 201)
    resp = api.get_pack(pk["id"], platform_admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    data = body["data"]
    assert data["sku"] == "P-ENV"
    assert data["certification_status"] == "DESIGN"
    assert data["version"] == 1


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the declared roles below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    set_clock()
    pf = create_platform(code="MX18")
    resp = api.create_pack(pack_payload(pf["id"], sku="P-AUTH"), None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_researcher_cannot_create_pack_returns_forbidden(api, field_researcher_headers):
    """PRD §2.1: "If the role is declared but is not authorized for the target
    endpoint, or an entity-backed ownership check fails, the request is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`ProductEngineer` alone creates battery packs, chargers, and tool
    models"

    Design: Corner/rbac/researcher_cannot_create_pack_returns_forbidden
    """
    set_clock()
    pf = create_platform(code="MX18")
    resp = api.create_pack(pack_payload(pf["id"], sku="P-RBAC"), field_researcher_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    rows, meta = validate_paginated(api.list_packs(field_researcher_headers,
                                                   params={"platform_id": pf["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_platform_sunset_and_retire_transitions_via_clock(api, product_engineer_headers, platform_admin_headers):
    """PRD §3.1: "`SUNSETTING` is advisory: pack and tool creation and tool
    launches all remain allowed, and the backward-commitment window check
    applies at launch when `sunset_date` is set. `RETIRED` is a hard lockdown —
    pack creation, tool creation, pack certification submission, and tool
    launch against a `RETIRED` platform are all rejected with
    `ERR_PLATFORM_RETIRED`."
    PRD §2.5: "Advancing the clock is the only force that moves a
    `BatteryPlatform` through its sunset lifecycle."

    Design: Corner/cross_cutting_complexity_layers/platform_sunset_and_retire_transitions_via_clock
    """
    set_clock()
    pf = validate_success(api.create_platform(
        platform_payload(code="MX18", sunset_announce_date="2026-10-01T00:00:00Z",
                         sunset_date="2026-12-01T00:00:00Z"),
        platform_admin_headers), 201)
    set_clock("2026-10-15T00:00:00Z")  # past announce, before sunset: SUNSETTING
    sunsetting_pack = api.create_pack(pack_payload(pf["id"], sku="P-SUN-1"),
                                      product_engineer_headers)
    validate_success(sunsetting_pack, 201)
    set_clock("2026-12-01T00:00:00Z")  # sunset_date reached: RETIRED
    retired_pack = api.create_pack(pack_payload(pf["id"], sku="P-SUN-2"),
                                   product_engineer_headers)
    validate_error(retired_pack, ApiErrorId.ERR_PLATFORM_RETIRED)
