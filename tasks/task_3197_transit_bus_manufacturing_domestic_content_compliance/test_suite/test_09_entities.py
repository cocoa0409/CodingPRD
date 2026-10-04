"""Corner tests: entity-level claims (defaults, uniqueness, enum constraints,
listing envelope, append-only inspection records)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_inspection_record,
    build_bus_to_plant_inspection,
    create_agency,
    create_agency_payload,
    create_component_payload,
    get_success_data,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
INSP = TEST_USERS["agency_inspector_headers"]


def test_agency_creation_applies_defaults(api):
    """PRD section 3.1: "The `federally_funded` flag, which defaults to true
    when not supplied, gates the entire Buy America compliance track: a
    federally funded agency's buses must carry accessibility safety equipment
    at engineering time and a passing domestic content certificate before they
    may be presented for plant inspection."
    PRD section 3.1: "Two optional fields capture the agency's electrification
    commitment: `fleet_transition_target_pct`, a target percentage of the
    fleet to be battery-electric by a target year, defaulting to 0, and
    `transition_target_year`, the year by which that percentage must be
    reached."
    PRD section 3.1: "A newly created agency starts in `ACTIVE` status with
    both of its zero-emission metrics, `zev_ratio` and
    `projected_zev_ratio`, at zero."

    Design: Corner/entities/agency_creation_defaults_applied
    """
    resp = api.create_agency(
        {"name": "Default Transit", "agency_code": "DFT1",
         "transition_target_year": 2035},
        ADMIN,
    )
    agency = validate_success(resp, expected_status=201)
    assert agency["federally_funded"] is True
    assert agency["fleet_transition_target_pct"] == 0
    assert agency["zev_ratio"] == 0
    assert agency["projected_zev_ratio"] == 0
    assert agency["status"] == "ACTIVE"
    assert agency["version"] == 1


def test_agency_duplicate_code_rejected(api):
    """PRD section 3.1: "The `agency_code` must be unique across all agencies;
    an attempt to register a code already in use is rejected with
    `ERR_DUPLICATE`."

    Design: Corner/entities/agency_duplicate_code_rejected
    """
    resp = api.create_agency(
        {"name": "First Transit", "agency_code": "DUP1",
         "transition_target_year": 2035},
        ADMIN,
    )
    validate_success(resp, expected_status=201)
    resp = api.create_agency(
        {"name": "Second Transit", "agency_code": "DUP1",
         "transition_target_year": 2036},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_agency_get_nonexistent_returns_not_found(api):
    """PRD section 2.5: "Third, existence: whether every resource referenced
    in the URL path exists, validated left to right along the path, failing as
    `ERR_NOT_FOUND`."

    Design: Corner/entities/agency_get_not_found
    """
    resp = api.get_agency(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_component_unknown_category_rejected(api):
    """PRD section 3.4: "A `ComplianceOfficer` (or `PlatformAdmin`) registers
    a component with its `name`, a `category` of exactly one of `PROPULSION`,
    `BODY`, `AXLE`, `ELECTRICAL`, `FARE`, or `ACCESSIBILITY`, a supplier
    `unit_cost_cents` in integer cents, and an `is_domestic` flag attesting
    domestic origin."
    PRD section 2.5: "A request that is malformed before any of these
    categories apply — a missing required field, a malformed value, or an
    unknown enum member — is rejected with `ERR_INVALID_REQUEST` (HTTP 400),
    and a business validation failure that fits no narrower category is
    rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/component_enum_category_constraint
    """
    resp = api.create_component(
        create_component_payload(category="HVAC"), CO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_agency_list_envelope_and_pagination_meta(api):
    """PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD section 2.3: "Paginated responses carry four fields in the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`, where `has_more`
    tells the caller whether additional pages exist beyond the returned
    window."

    Design: Corner/entities/agency_list_pagination_envelope
    """
    resp = api.create_agency(
        {"name": "Paged Transit", "agency_code": "PGT1",
         "transition_target_year": 2035},
        ADMIN,
    )
    validate_success(resp, expected_status=201)

    resp = api.list_agencies(ADMIN)
    body = resp.json()
    assert resp.status_code == 200
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)
    assert "api_request_id" in body["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in body["meta"], f"pagination meta must carry {field}"
    codes = [a["agency_code"] for a in body["data"]]
    assert "PGT1" in codes


def test_inspection_record_carries_no_version_or_updated_at(api):
    """PRD section 2.4: "The one exception is the `InspectionRecord` entity:
    an inspection is an immutable observation written once, so an
    `InspectionRecord` carries only `id` and `created_at` — it has no
    `updated_at` and no `version`."

    Design: Corner/entities/inspection_record_immutable_no_version
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_plant_inspection(setup)
    resp = api.create_inspection_record(
        {"bus_unit_id": bus["id"], "inspection_type": "PLANT",
         "inspector_id": "insp-1", "result": "PASS"},
        INSP,
    )
    record = validate_success(resp, expected_status=201)
    assert_inspection_record(record)

    resp = api.get_inspection_record(record["id"], INSP)
    record = validate_success(resp)
    assert_inspection_record(record)
