"""Corner coverage — entities (PRD §2.2 envelope, §2.5 common properties,
§3.1 standards, §3.2 families, §3.4 units, §3.7 claim shape).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_list_sorted_by_created_at,
    assert_regulation_standard,
    create_engine_family_payload,
    create_family,
    create_published_standard,
    create_regulation_standard_payload,
    create_warranty_claim_payload,
    is_iso8601_timestamp,
    make_fleet_manager_headers,
    set_logical_clock,
    setup_engine_unit,
    setup_full_environment,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_PAYLOAD = {
    "code": "EPA2027-HD",
    "nox_limit_g_per_bhp_hr": 0.35,
    "pm_limit_g_per_bhp_hr": 0.01,
    "useful_life_miles": 435000,
    "useful_life_hours": 22000,
    "useful_life_years": 10,
    "base_warranty_years": 2,
    "base_warranty_miles": 50000,
    "effective_model_year_first": 2027,
    "effective_model_year_last": 2030,
}


def test_standard_create_returns_201_draft_with_system_defaults(api, admin_headers):
    """PRD §3.1: "A new standard starts in `DRAFT` status with `published_at` unset and `successor_standard_id` unset."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by system cascades rather than direct client action."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §4: "Operations that create a new resource return a `201 Created` status code"

    A standard created with the full field set returns 201 with status DRAFT,
    null published_at and successor_standard_id, version 1, server-minted
    id/created_at/updated_at, and the envelope carries meta.api_request_id.

    Design: Corner/entities/standard_create_returns_201_draft_with_system_defaults
    """
    resp = api.create_regulation_standard(dict(STANDARD_PAYLOAD), admin_headers)
    data = validate_success(resp, 201)
    assert_regulation_standard(data)
    assert data["status"] == "DRAFT", f"new standard must start DRAFT, got {data['status']}"
    assert data["version"] == 1, f"a freshly created resource is at version 1, got {data['version']}"
    assert data["published_at"] is None, f"published_at must be unset, got {data['published_at']!r}"
    assert data["successor_standard_id"] is None, (
        f"successor_standard_id must be unset, got {data['successor_standard_id']!r}"
    )
    body = resp.json()
    assert body.get("response_type") == "object", (
        f"a single created resource is an object response, got {body.get('response_type')!r}"
    )
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp must be an ISO 8601 timestamp"
    )


def test_standard_get_round_trips_every_posted_field(api, admin_headers, officer_headers):
    """PRD §3.1: "A `PlatformAdmin` creates one by supplying its `code` — unique across the entire program, so a duplicate submission is rejected with `ERR_DUPLICATE_STANDARD_CODE` (HTTP 409) — together with the certification limits `nox_limit_g_per_bhp_hr` and `pm_limit_g_per_bhp_hr`, the useful-life obligations `useful_life_miles`, `useful_life_hours`, and `useful_life_years`, the base warranty terms `base_warranty_years` and `base_warranty_miles`, and the effective window expressed as the integers `effective_model_year_first` and `effective_model_year_last`."

    Every posted configuration value (limits, useful-life triple, base warranty
    pair, model-year window) round-trips byte-identical through GET.

    Design: Corner/entities/standard_get_round_trips_every_posted_field
    """
    created = validate_success(
        api.create_regulation_standard(dict(STANDARD_PAYLOAD), admin_headers), 201
    )
    fetched = validate_success(api.get_regulation_standard(created["id"], officer_headers))
    assert_regulation_standard(fetched)
    for field, expected in STANDARD_PAYLOAD.items():
        assert fetched[field] == expected, (
            f"round-trip mismatch on {field}: posted {expected!r}, read {fetched[field]!r}"
        )


def test_engine_families_list_paginates_total_count_and_has_more(api, engineer_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when it is not provided it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.2: "The engine-family list endpoint itself supports filtering by `regulation_standard_id` and by `certification_status`."

    With three DESIGN families on one standard, limit=2&offset=0 returns 2 rows
    with total_count 3 and has_more true, offset=2 returns 1 row with has_more
    false, and the certification_status filter narrows the counted set.

    Design: Corner/entities/engine_families_list_paginates_total_count_and_has_more
    """
    standard = create_published_standard()
    for code, year in (("F-A", 2027), ("F-B", 2027), ("F-C", 2028)):
        create_family(
            standard["id"],
            family_code=code,
            model_year=year,
        )

    page1, meta1 = validate_paginated(
        api.list_engine_families(engineer_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"limit=2 must return 2 rows, got {len(page1)}"
    assert meta1["total_count"] == 3 and meta1["has_more"] is True, (
        f"page 1 of 3 with limit 2: total_count 3 / has_more true expected, got {meta1}"
    )
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_engine_families(engineer_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"offset=2 with 3 total must return 1 row, got {len(page2)}"
    assert meta2["total_count"] == 3 and meta2["has_more"] is False, (
        f"last page: total_count 3 / has_more false expected, got {meta2}"
    )

    filtered, meta_f = validate_paginated(
        api.list_engine_families(engineer_headers, params={"certification_status": "DESIGN"})
    )
    assert len(filtered) == 3 and meta_f["total_count"] == 3, (
        f"all three families are DESIGN, got {len(filtered)} rows"
    )
    assert_list_sorted_by_created_at(filtered)

    default_page, meta_d = validate_paginated(api.list_engine_families(engineer_headers))
    assert len(default_page) == 3
    assert meta_d["limit"] == 10 and meta_d["offset"] == 0, (
        f"defaults are limit 10 / offset 0, got limit {meta_d['limit']} / offset {meta_d['offset']}"
    )


def test_engine_unit_get_with_unknown_id_returns_not_found(api, admin_headers):
    """PRD §2.8: "Existence: path identifiers first, then foreign-key identifiers in the body, validated left-to-right (`ERR_NOT_FOUND`)."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    A syntactically valid but never-allocated UUID in the path yields 404
    ERR_NOT_FOUND, not a 400 and not an empty object.

    Design: Corner/entities/engine_unit_get_with_unknown_id_returns_not_found
    """
    resp = api.get_engine_unit(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_claim_create_missing_required_amount_returns_invalid_request(
    api, admin_headers, officer_headers
):
    """PRD §3.7: "The payload names the `engine_unit_id`, the `service_center_id`, the `failed_component_class`, the OEM `failure_code`, and the `claimed_amount_cents`, which must be greater than 0."
    PRD §2.8: "Request shape: required fields present, enum values within their declared sets, integer ranges respected"
    PRD §3.7: "The claims list endpoint supports filtering by `engine_unit_id`, `service_center_id`, and `status`."

    Omitting the required claimed_amount_cents from an otherwise valid claim
    yields 400 ERR_INVALID_REQUEST at the request-shape gate before any state
    or coverage logic runs, and no claim row exists afterwards.

    Design: Corner/entities/claim_create_missing_required_amount_returns_invalid_request
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")

    payload = create_warranty_claim_payload(
        engine_unit_id=unit["id"],
        service_center_id=env["center"]["id"],
        failed_component_class="ENGINE_BASE",
        failure_code="FC-miss",
    )
    del payload["claimed_amount_cents"]
    resp = api.create_warranty_claim(payload, make_fleet_manager_headers(env["fleet"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    claims, meta = validate_paginated(
        api.list_warranty_claims(officer_headers, params={"engine_unit_id": unit["id"]})
    )
    assert claims == [] and meta["total_count"] == 0, (
        f"no claim row may exist after a shape rejection, got {claims}"
    )


def test_family_create_with_invalid_enum_architecture_returns_invalid_request(
    api, engineer_headers
):
    """PRD §3.2: "the aftertreatment `architecture` — one of `DOC_DPF_SCR`, `DOC_DPF_SCR_ASC`, or `EGR_DOC_DPF_SCR`"
    PRD §2.8: "Request shape: required fields present, enum values within their declared sets, integer ranges respected"

    An architecture value outside {DOC_DPF_SCR, DOC_DPF_SCR_ASC,
    EGR_DOC_DPF_SCR} is rejected 400 ERR_INVALID_REQUEST at the shape gate.

    Design: Corner/entities/family_create_with_invalid_enum_architecture_returns_invalid_request
    """
    standard = create_published_standard()
    resp = api.create_engine_family(
        create_engine_family_payload(
            regulation_standard_id=standard["id"],
            family_code="F-BAD",
            model_year=2027,
            architecture="WANKEL",
        ),
        engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
