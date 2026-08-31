"""Registering jurisdictions, inspectors and parcels, and the response envelope."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    assert_jurisdiction, assert_inspector, assert_property, assert_availability,
    assert_no_type_prefix, is_iso8601_timestamp,
    jurisdiction_payload,
    register_jurisdiction, register_property, open_project,
    PLATFORM_ADMIN, DESIGN_LEAD, PROJECT_MANAGER, FINANCE_ADVISOR,
)


def test_register_jurisdiction_returns_created_ordinance_row(api):
    """PRD §4: "Creating a new resource returns HTTP 201; every other successful
    operation, including state transitions that modify an existing resource and
    every read, returns HTTP 200."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, whether the mutation was
    requested directly or arrived as a cascade from somewhere else."
    PRD §2.4: "Identifiers are UUID strings with no type prefix of any kind — an ADU
    project's identifier looks exactly like an inspector's."

    Design: Corner/entities/create_jurisdiction_returns_201_with_ordinance_fields
    """
    payload = jurisdiction_payload()
    data = validate_success(api.create_jurisdiction(payload, PLATFORM_ADMIN), 201)

    assert_jurisdiction(data)
    assert data["code"] == "PLMD"
    assert data["local_max_detached_sqft"] == 1000
    assert data["version"] == 1, f"a freshly created row starts at version 1, got {data['version']}"
    assert_no_type_prefix(data["id"])


def test_register_jurisdiction_without_optional_fields_uses_declared_defaults(api):
    """PRD §3.1: "Four further fields have defaults and may be omitted:
    `correction_response_days`, the number of calendar days an applicant has to answer
    a corrections letter, defaults to 60 and must be at least 1; `separate_meter_required`
    defaults to false and is true only where the ordinance forbids shared metering for
    new detached units; `str_min_lease_days`, the shortest lease term the ordinance
    permits for an ADU, defaults to 30 and must be at least 1; and `str_prohibited`
    defaults to false and is true where short-term rental of an ADU is barred outright."

    Design: Corner/entities/create_jurisdiction_omitting_optionals_applies_declared_defaults
    """
    payload = {
        "name": "Modesto", "code": "MDST", "local_max_detached_sqft": 900,
        "local_rear_setback_ft": 5.0, "local_side_setback_ft": 5.0,
        "local_max_height_ft": 16.0, "plan_check_base_fee_cents": 100_000,
        "plan_check_rate_per_sqft_cents": 80, "impact_fee_per_sqft_cents": 700,
        "utility_capacity_fee_cents": 200_000,
    }
    data = validate_success(api.create_jurisdiction(payload, PLATFORM_ADMIN), 201)

    assert data["correction_response_days"] == 60
    assert data["separate_meter_required"] is False
    assert data["str_min_lease_days"] == 30
    assert data["str_prohibited"] is False


def test_register_inspector_without_optional_fields_uses_declared_defaults(api):
    """PRD §3.1: "Two optional fields round out the record: `daily_capacity`, the maximum
    number of appointments the inspector may hold on any one calendar date, which defaults
    to 4 and must lie between 1 and 12 inclusive; and `status`, which is either `ACTIVE`
    or `INACTIVE` and defaults to `ACTIVE`."
    PRD §3.1: "Anyone may also ask what an inspector's day looks like by naming a
    `slot_date`, and the answer reports that inspector's `inspector_id`, the `slot_date`
    asked about, their `daily_capacity`, a `booked_count` counting only appointments still
    in `SCHEDULED` or `PARTIAL`, and the `remaining_slots` left over."

    Design: Corner/entities/create_inspector_omitting_daily_capacity_defaults_to_four
    """
    jurisdiction = register_jurisdiction(api)
    payload = {"jurisdiction_id": jurisdiction["id"], "full_name": "M. Duong",
               "certifications": ["STRUCTURAL", "FINAL"]}

    inspector = validate_success(api.create_inspector(payload, PLATFORM_ADMIN), 201)
    assert_inspector(inspector)
    assert inspector["daily_capacity"] == 4
    assert inspector["status"] == "ACTIVE"

    day = validate_success(
        api.get_inspector_availability(inspector["id"], "2026-09-02", PROJECT_MANAGER))
    assert_availability(day, inspector["id"], "2026-09-02", daily_capacity=4, booked_count=0)


def test_read_parcel_returns_stored_lot_and_service_data(api):
    """PRD §3.1: "Each parcel names its `jurisdiction_id` and its `address_line`, and
    describes the physical lot with `lot_sqft` and `existing_dwelling_sqft`, both of which
    must be strictly greater than zero."
    PRD §3.1: "Three optional fields carry defaults: `occupied`, true when the family is
    still living in the front house during construction, defaults to true; `in_str_overlay`,
    true when the parcel sits inside a short-term-rental restriction overlay, defaults to
    false; and `existing_mortgage_balance_cents`, the outstanding first-lien balance,
    defaults to 0 and may not be negative."

    Design: Corner/entities/get_property_by_id_returns_stored_row
    """
    jurisdiction = register_jurisdiction(api)
    payload = {
        "jurisdiction_id": jurisdiction["id"], "address_line": "12 Sage Ct",
        "lot_sqft": 8_000, "existing_dwelling_sqft": 1_450,
        "electrical_service_amps": 400, "existing_water_meter_size_in": 1.0,
        "pre_adu_value_cents": 80_000_000,
    }
    parcel = validate_success(api.create_property(payload, DESIGN_LEAD), 201)

    response = api.get_property(parcel["id"], FINANCE_ADVISOR)
    data = validate_success(response)
    assert response.json()["response_type"] == "object"
    assert_property(data)
    assert data["lot_sqft"] == 8_000
    assert data["existing_dwelling_sqft"] == 1_450
    assert data["electrical_service_amps"] == 400
    assert data["existing_water_meter_size_in"] == 1.0
    assert data["occupied"] is True
    assert data["in_str_overlay"] is False
    assert data["existing_mortgage_balance_cents"] == 0


def test_register_parcel_without_lot_sqft_is_rejected(api):
    """PRD §2.7: "**Request shape.** Required fields present and correctly typed; enum-typed
    fields carrying a member of their declared set; numeric, range, and format constraints
    satisfied; pagination bounds satisfied on list endpoints. Every failure here is
    `ERR_VALIDATION` (HTTP 422)."
    PRD §3.1: "Each parcel names its `jurisdiction_id` and its `address_line`, and describes
    the physical lot with `lot_sqft` and `existing_dwelling_sqft`, both of which must be
    strictly greater than zero."

    Design: Corner/entities/create_property_missing_lot_sqft_returns_validation
    """
    jurisdiction = register_jurisdiction(api)
    payload = {
        "jurisdiction_id": jurisdiction["id"], "address_line": "12 Sage Ct",
        "existing_dwelling_sqft": 1_450, "electrical_service_amps": 400,
        "existing_water_meter_size_in": 1.0, "pre_adu_value_cents": 80_000_000,
    }

    validate_error(api.create_property(payload, DESIGN_LEAD), ApiErrorId.ERR_VALIDATION)

    rows, meta = validate_paginated(
        api.list_properties(PLATFORM_ADMIN, {"jurisdiction_id": jurisdiction["id"]}))
    assert meta["total_count"] == 0, "a rejected registration must persist nothing"


def test_second_jurisdiction_reusing_a_code_is_rejected(api):
    """PRD §3.1: "A jurisdiction registration carries a human-readable `name` and a short
    `code` — 2 to 8 characters, uppercase letters and digits only — that must be unique
    across every jurisdiction on record; a second attempt to use a code that is already
    taken is rejected with `ERR_DUPLICATE_JURISDICTION_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_jurisdiction_code_returns_conflict
    """
    first = register_jurisdiction(api)

    clash = jurisdiction_payload(name="Palmdale Annex", local_max_detached_sqft=800,
                                 local_rear_setback_ft=5.0, local_side_setback_ft=5.0,
                                 local_max_height_ft=16.0, plan_check_base_fee_cents=110_000,
                                 plan_check_rate_per_sqft_cents=85,
                                 impact_fee_per_sqft_cents=750,
                                 utility_capacity_fee_cents=240_000)
    validate_error(api.create_jurisdiction(clash, PLATFORM_ADMIN),
                   ApiErrorId.ERR_DUPLICATE_JURISDICTION_CODE)

    unchanged = validate_success(api.get_jurisdiction(first["id"], PLATFORM_ADMIN))
    assert unchanged["local_max_detached_sqft"] == 1000, "the incumbent row must be untouched"


def test_pagination_limit_above_the_maximum_is_rejected(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, may be no smaller than 1, and may be
    no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit`
    outside the range of 1 through 100, or a negative `offset`, is rejected with
    `ERR_VALIDATION` (HTTP 422) — the service does not silently clamp out-of-range
    pagination."

    Design: Corner/validations/pagination_limit_above_max_returns_validation
    """
    validate_error(api.list_adu_projects(PLATFORM_ADMIN, {"limit": 101, "offset": 0}),
                   ApiErrorId.ERR_VALIDATION)


def test_project_listing_reports_window_and_total(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they
    were applied, `total_count` giving the number of rows matching the filters before the
    window was applied, and `has_more`, which is true when rows remain beyond the returned
    window."
    PRD §3.2: "Project listings may be narrowed by `property_id` and by lifecycle `status`."

    Design: Corner/entities/list_adu_projects_returns_pagination_envelope
    """
    jurisdiction = register_jurisdiction(api)
    parcel = register_property(api, jurisdiction["id"])
    open_project(api, parcel["id"])
    open_project(api, parcel["id"], unit_type="CONVERSION", proposed_sqft=500,
                 proposed_height_ft=12.0, rear_setback_ft=4.0, side_setback_ft=4.0,
                 bedrooms=1, contract_base_price_cents=15_000_000)

    response = api.list_adu_projects(PLATFORM_ADMIN, {"property_id": parcel["id"],
                                                     "limit": 1, "offset": 0})
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert len(rows) == 1, f"limit 1 must return exactly one element, got {len(rows)}"


def test_read_unknown_project_reports_project_not_found(api):
    """PRD §2.5: "Each entity has its own not-found identifier, all of them HTTP 404:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_CORRECTION_ITEM_NOT_FOUND`,
    `ERR_UTILITY_CONNECTION_NOT_FOUND`, `ERR_FINANCING_SCENARIO_NOT_FOUND`,
    `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, and `ERR_APPOINTMENT_NOT_FOUND`."

    Design: Corner/entities/get_adu_project_unknown_id_returns_project_not_found
    """
    response = api.get_adu_project(NON_EXISTENT_UUID, PLATFORM_ADMIN)

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND)
    assert response.json()["response_type"] == "error"


def test_success_and_error_bodies_both_carry_the_meta_block(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with three
    fractional digits."

    Design: Corner/consistency_model/success_and_error_envelopes_carry_meta_block
    """
    created = api.create_jurisdiction(jurisdiction_payload(), PLATFORM_ADMIN)
    body = created.json()
    data = validate_success(created, 201)

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert is_iso8601_timestamp(data["created_at"])
    assert data["created_at"].endswith("Z") and "." in data["created_at"]
    assert len(data["created_at"].split(".")[1].rstrip("Z")) == 3, (
        f"created_at must carry three fractional digits, got {data['created_at']}")

    missing = api.get_property(NON_EXISTENT_UUID, PLATFORM_ADMIN)
    error_body = missing.json()
    error_data = validate_error(missing, ApiErrorId.ERR_PROPERTY_NOT_FOUND)

    assert error_body["response_type"] == "error"
    assert error_data["message"].strip(), "an error body must carry a human-readable message"
    assert error_body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(error_body["meta"]["api_request_timestamp"])
