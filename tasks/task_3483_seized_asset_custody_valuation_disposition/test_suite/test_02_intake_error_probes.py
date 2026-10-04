"""Intake error probes: authentication, authorization, request shape,
existence, and case-number uniqueness."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_asset_payload,
    create_case,
    create_case_payload,
    create_valuation_payload,
    get_asset,
    intake_asset,
    make_claimant_headers,
    validate_error,
    validate_paginated,
)


def test_asset_get_unknown_id_returns_not_found(api):
    """PRD §2.10: "**Existence** — path identifiers and body foreign-key
    identifiers resolve to existing resources, validated left to right; the
    first unresolvable identifier yields `ERR_NOT_FOUND`."

    Design: Corner/entities/asset_get_unknown_id_returns_not_found
    """
    resp = api.get_asset(NON_EXISTENT_UUID, TEST_USERS["asset_manager_headers"])
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert isinstance(err["message"], str) and err["message"].strip()


def test_asset_create_missing_asset_type_invalid_request(api):
    """PRD §2.10: "**Request shape** — required fields are present, enum
    values are in-domain, integers are positive where required ... failures
    are `ERR_INVALID_REQUEST`."
    PRD §3.2: an intake payload names "the owning `seizure_case_id`, the
    `asset_type` ..., a free-text `description`, the `seized_on` timestamp of
    physical seizure ..., and the `seizure_condition_grade` recorded at
    intake".

    Design: Corner/entities/asset_create_missing_asset_type_invalid_request
    """
    case = create_case(
        case_number="26-MJ-1005", judicial_district="D. Del.",
        forfeiture_type="CIVIL", lead_agency_code="IRS",
    )
    payload = {
        "seizure_case_id": case["id"],
        "description": "no type given",
        "seized_on": "2026-09-01T00:00:00Z",
        "seizure_condition_grade": "GOOD",
    }
    resp = api.create_asset(payload, TEST_USERS["asset_custodian_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    rows, meta = validate_paginated(
        api.list_case_assets(case["id"], TEST_USERS["asset_custodian_headers"])
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a shape-rejected intake must create nothing"
    )


def test_asset_type_invalid_enum_rejected(api):
    """PRD §2.10: "**Request shape** — required fields are present, enum
    values are in-domain ... failures are `ERR_INVALID_REQUEST`."
    PRD §3.2: the `asset_type` is "one of `REAL_PROPERTY`, `BUSINESS`,
    `VEHICLE`, `VESSEL`, `AIRCRAFT`, `PERSONAL_PROPERTY`,
    `FINANCIAL_INSTRUMENT`".

    Design: Corner/entities/asset_type_invalid_enum_rejected
    """
    case = create_case(
        case_number="26-MJ-1009", judicial_district="E.D.N.Y.",
        forfeiture_type="CIVIL", lead_agency_code="HSI",
    )
    payload = create_asset_payload(
        case["id"], asset_type="REAL_ESTATE", description="bad enum",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    resp = api.create_asset(payload, TEST_USERS["asset_custodian_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def test_asset_create_unknown_case_returns_not_found(api):
    """PRD §2.10: "**Existence** — path identifiers and body foreign-key
    identifiers resolve to existing resources, validated left to right; the
    first unresolvable identifier yields `ERR_NOT_FOUND`."

    Design: Corner/entities/asset_create_unknown_case_returns_not_found
    """
    payload = create_asset_payload(
        NON_EXISTENT_UUID, asset_type="VEHICLE", description="orphan",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    resp = api.create_asset(payload, TEST_USERS["asset_custodian_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_unrecognized_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role
    outside this list, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/unrecognized_role_header_unauthenticated
    """
    resp = api.create_case(
        create_case_payload(
            case_number="26-MJ-1020", judicial_district="D. Or.",
            forfeiture_type="CIVIL", lead_agency_code="DEA",
        ),
        build_user_headers("nobody", "BogusRole"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_claimant_cannot_create_valuation(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §3.3: "An `Appraiser` — who submits valuations and never adjudicates
    them — files a valuation for an asset"

    Design: Corner/validations/claimant_cannot_create_valuation
    """
    case = create_case(
        case_number="26-MJ-1021", judicial_district="D. Colo.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="e-bike",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    payload = create_valuation_payload(
        asset["id"], asset["version"], method="BLUE_BOOK",
        raw_value_cents=300_000, assessed_condition_grade="GOOD",
    )
    resp = api.create_valuation(payload, make_claimant_headers("cl-orma"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
    rows, meta = validate_paginated(
        api.list_asset_valuations(asset["id"], TEST_USERS["asset_manager_headers"])
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a role-rejected valuation must not be created"
    )
    assert get_asset(asset["id"])["legal_state"] == "SEIZED"


def test_role_and_shape_checks_beat_existence(api):
    """PRD §2.10: "Every request is evaluated against an ordered pipeline of
    checks, and the first failure wins: the response carries the error of the
    earliest tier that fails, and later tiers are never consulted."
    PRD §2.10: authorization (tier 2) and request shape (tier 3) both precede
    "4. **Existence** — path identifiers and body foreign-key identifiers
    resolve to existing resources, validated left to right".

    Design: Corner/validations/role_and_shape_checks_beat_existence
    """
    case = create_case(
        case_number="26-MJ-1022", judicial_district="E.D.N.Y.",
        forfeiture_type="CIVIL", lead_agency_code="HSI",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="decoy",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    # Claimant (role not in the endpoint's list) against a NON-EXISTENT asset:
    # authorization fires before existence.
    role_probe = api.create_valuation(
        create_valuation_payload(
            NON_EXISTENT_UUID, asset["version"], method="BLUE_BOOK",
            raw_value_cents=300_000, assessed_condition_grade="GOOD",
        ),
        make_claimant_headers("cl-orma"),
    )
    validate_error(role_probe, ApiErrorId.ERR_FORBIDDEN)
    assert role_probe.status_code == 403
    # Shape-invalid body (missing description) against a NON-EXISTENT case:
    # request shape fires before existence.
    shape_probe = api.create_asset(
        {
            "seizure_case_id": NON_EXISTENT_UUID,
            "asset_type": "VEHICLE",
            "seized_on": "2026-09-01T00:00:00Z",
            "seizure_condition_grade": "GOOD",
        },
        TEST_USERS["asset_custodian_headers"],
    )
    validate_error(shape_probe, ApiErrorId.ERR_INVALID_REQUEST)
    assert shape_probe.status_code == 400


def test_duplicate_case_number_rejected(api):
    """PRD §3.1: "Case numbers are unique across all cases: opening a case
    whose `case_number` is already taken is rejected with
    `ERR_DUPLICATE_CASE_NUMBER`."

    Design: Corner/errors/duplicate_case_number_rejected
    """
    create_case(
        case_number="26-MJ-1027", judicial_district="S.D.N.Y.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    resp = api.create_case(
        create_case_payload(
            case_number="26-MJ-1027", judicial_district="N.D. Cal.",
            forfeiture_type="CRIMINAL", lead_agency_code="FBI",
        ),
        TEST_USERS["case_agent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)
    assert resp.status_code == 409
