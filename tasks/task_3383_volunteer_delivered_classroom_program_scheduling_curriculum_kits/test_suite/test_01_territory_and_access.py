"""Territory foundations, envelope rules, and access control (PRD §2.1-§2.8, §3.1)."""
from test_helpers import (
    ADMIN,
    DIRECTOR,
    FUNDER,
    LOGISTICS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_district,
    assert_kit_inventory,
    assert_school,
    district_payload,
    kit_inventory_payload,
    make_area_office,
    make_district,
    make_inventory,
    make_program,
    make_school,
    program_catalog_payload,
    transition_district,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_district_create_returns_declared_fields_and_starts_prospect(api):
    """PRD §3.1: "An `AreaDirector` then cultivates districts under an office by
    supplying the managing `area_office_id` and the district `name`. A new
    district starts in PROSPECT."
    PRD §2.5: "`id` is a server-minted UUID with no type prefix. `created_at`
    and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional
    digits."

    Design: Corner/entities/corner_district_create_returns_declared_fields_and_starts_prospect
    """
    office = make_area_office()
    resp = api_client.create_district(district_payload(office["id"], name="Riverview Unified"), DIRECTOR)
    data = validate_success(resp, 201)
    assert_district(data)
    assert data["relationship_status"] == "PROSPECT"
    assert data["name"] == "Riverview Unified"
    assert data["area_office_id"] == office["id"]


def test_school_get_round_trips_stored_fields(api):
    """PRD §3.1: "The `AreaDirector` registers a school with its owning
    `district_id`, a `name`, the grade span it serves from `grade_band_low`
    (the lowest grade, between 1 and 12) to `grade_band_high` (no lower than
    the low end), and the `instructional_days` on which classroom sessions may
    run — each entry drawn from MON, TUE, WED, THU, or FRI."

    Design: Corner/entities/corner_school_get_round_trips_stored_fields
    """
    office = make_area_office()
    district = make_district(office["id"], activate=False)
    school = make_school(district["id"], grade_band_low=1, grade_band_high=5)
    resp = api_client.get_school(school["id"], FUNDER)
    data = validate_success(resp, 200)
    assert_school(data)
    assert data["grade_band_low"] == 1
    assert data["grade_band_high"] == 5
    assert data["instructional_days"] == ["MON", "TUE", "WED", "THU", "FRI"]
    assert data["district_id"] == district["id"]


def test_area_office_district_quota_enforced_at_cap(api):
    """PRD §3.1: "The territory cap is enforced at creation: if the office
    already manages `max_districts` districts whose `relationship_status` is
    anything other than CHURNED, the create is rejected with
    `ERR_TERRITORY_LIMIT_REACHED` — the count of non-churned districts must
    remain strictly below the cap for the addition to succeed."

    Design: Corner/entities/corner_area_office_district_quota_enforced_at_cap
    """
    office = make_area_office(name="Small Office", region_code="RURAL", max_districts=2)
    d1 = api_client.create_district(district_payload(office["id"], name="District One"), DIRECTOR)
    validate_success(d1, 201)
    d2 = api_client.create_district(district_payload(office["id"], name="District Two"), DIRECTOR)
    validate_success(d2, 201)
    resp = api_client.create_district(district_payload(office["id"], name="District Three"), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_LIMIT_REACHED)
    rows, meta = validate_paginated(api_client.list_districts(FUNDER, params={"area_office_id": office["id"]}))
    assert len(rows) == 2, f"office must still hold exactly 2 districts, got {len(rows)}"


def test_immediate_consistency_read_after_write(api):
    """PRD §2.5: "`updated_at` refreshes on every mutation. `version` is a
    system-managed integer that increments by 1 on every mutation of the
    resource."
    PRD §3.1: "ACTIVATE moves PROSPECT to PARTNER."

    Design: Corner/consistency_model/corner_immediate_consistency_read_after_write
    """
    office = make_area_office()
    created = make_district(office["id"], activate=False)
    resp = api_client.transition_district(created["id"], {"action": "ACTIVATE"}, DIRECTOR)
    after = validate_success(resp, 200)
    assert after["relationship_status"] == "PARTNER"
    readback = validate_success(api_client.get_district(created["id"], FUNDER), 200)
    assert readback["relationship_status"] == "PARTNER"
    assert readback["version"] == after["version"], "read-after-write must agree on version"
    assert after["version"] == created["version"] + 1, "one mutation increments version by 1"
    assert readback["updated_at"] >= created["updated_at"]


def test_district_churned_terminal_lockdown_rejected(api):
    """PRD §3.1: "CHURN moves either PARTNER or AT_RISK to CHURNED, the
    terminal state — both churn branches behave identically."
    PRD §2.7: "State legality: the target entity is in a state from which the
    requested transition or action is defined, including terminal-state
    lockdown, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_district_churned_terminal_lockdown_rejected
    """
    office = make_area_office()
    district = make_district(office["id"], activate=True)
    transition_district(district["id"], "CHURN")
    resp = api_client.transition_district(district["id"], {"action": "FLAG_RISK"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    readback = validate_success(api_client.get_district(district["id"], FUNDER), 200)
    assert readback["relationship_status"] == "CHURNED"


def test_district_create_missing_auth_unauthenticated(api):
    """PRD §2.1: "A request with a missing or unrecognized header is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/corner_district_create_missing_auth_unauthenticated
    """
    office = make_area_office()
    resp = api_client.create_district(
        district_payload(office["id"], name="No Auth Unified"), headers={}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    rows, meta = validate_paginated(api_client.list_districts(FUNDER))
    assert len(rows) == 0, "no district may be created by an unauthenticated request"


def test_funder_create_district_forbidden(api):
    """PRD §2.1: "Once authenticated, a role may invoke only the operations
    assigned to it; any other attempt is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "A `Funder` holds no write operations at all."

    Design: Corner/validations/corner_funder_create_district_forbidden
    """
    office = make_area_office()
    resp = api_client.create_district(district_payload(office["id"], name="Funder Unified"), FUNDER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    rows, meta = validate_paginated(api_client.list_districts(FUNDER, params={"area_office_id": office["id"]}))
    assert len(rows) == 0


def test_district_transition_unknown_action_rejected(api):
    """PRD §2.7: "Body shape: required fields are present, no undeclared fields
    appear, enum and `action` values are recognized, and scalar ranges are sane
    — minutes in range, dates parseable — else `ERR_VALIDATION`."

    Design: Corner/validations/corner_district_transition_unknown_action_rejected
    """
    office = make_area_office()
    district = make_district(office["id"], activate=False)
    resp = api_client.transition_district(district["id"], {"action": "FROB"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    readback = validate_success(api_client.get_district(district["id"], FUNDER), 200)
    assert readback["relationship_status"] == "PROSPECT"


def test_program_create_invalid_capstone_facility_enum_rejected(api):
    """PRD §3.4: "a `capstone_facility` of SIMULATED_TOWN, FINANCE_PARK, or
    NONE — NONE exactly when `capstone_required` is false and a real facility
    when it is true, any other combination rejected as `ERR_VALIDATION`"
    PRD §2.7: "Body shape: required fields are present, no undeclared fields
    appear, enum and `action` values are recognized, and scalar ranges are sane
    — minutes in range, dates parseable — else `ERR_VALIDATION`."

    Design: Corner/entities/corner_program_create_invalid_capstone_facility_enum_rejected
    """
    bad_enum = api_client.create_program_catalog(
        program_catalog_payload(code="JA-BAD", capstone_required=True, capstone_facility="CASTLE"),
        ADMIN,
    )
    validate_error(bad_enum, ApiErrorId.ERR_VALIDATION)
    inconsistent = api_client.create_program_catalog(
        program_catalog_payload(code="JA-BAD2", capstone_required=True, capstone_facility="NONE"),
        ADMIN,
    )
    validate_error(inconsistent, ApiErrorId.ERR_VALIDATION)


def test_session_get_unknown_id_returns_not_found(api):
    """PRD §2.8: "When a request carries a resource identifier in its path —
    `district_id`, `school_id`, `partner_id`, `volunteer_id`, `program_id`,
    `agreement_id`, `delivery_id`, `session_id`, `inventory_id`, `capstone_id`,
    or `student_id` — existence is validated left-to-right, and the first
    identifier that does not correspond to an existing resource rejects the
    request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/corner_session_get_unknown_id_returns_not_found
    """
    resp = api_client.get_session(NON_EXISTENT_UUID, FUNDER)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert "message" in err, "error data must carry a human-readable message (PRD §2.2)"
