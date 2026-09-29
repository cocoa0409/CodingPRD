"""Entity surfaces: declared fields, defaults, derivations and reference integrity.

Each test here exercises one resource surface of the underwriting API — what a
creation echoes back, what a read re-derives, which inputs the server owns rather
than the client, and how a reference that names nothing (or names the wrong
parent) is refused.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    AcquisitionSource,
    AircraftClass,
    ApiErrorId,
    AssessmentVerdict,
    CoverageStatus,
    LossType,
    PilotBand,
    PolicyStatus,
    PolicyType,
    TerritorialLimit,
    TxnBasis,
    TxnType,
    UseClass,
    WarrantyBasis,
    WarrantyStatus,
    assert_aircraft_shape,
    assert_claim_shape,
    assert_damage_assessment_shape,
    assert_field_values,
    assert_fields_present,
    assert_immutable_common_fields,
    assert_instants_equal,
    assert_ledger_row,
    assert_operator_shape,
    assert_ordered_by_created_at,
    assert_pilot_shape,
    assert_policy_number_format,
    assert_policy_shape,
    assert_premium_transaction_shape,
    assert_request_meta,
    assert_schedule_shape,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------
def test_operator_registration_returns_the_whole_declared_field_set(api):
    """PRD §2.4: "Every resource carries a server-minted `id` that is a UUID string
    with no type prefix, and a `created_at` timestamp recording the instant the row
    was written."

    Design: Corner/entities/corner_operator_creation_returns_every_declared_field
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    payload = f.operator_payload()

    response = api.create_operator(payload, headers=users.UNDERWRITER)
    operator = validate_unpaginated(response, expected_status=201)

    assert_request_meta(response)
    assert_operator_shape(operator)
    assert_fields_present(operator, a.OPERATOR_FIELDS)
    assert_field_values(
        operator,
        legal_name=payload["legal_name"],
        operator_type=payload["operator_type"],
        home_base_icao=payload["home_base_icao"],
    )


def test_a_flight_school_needs_no_certificate_number_and_starts_with_no_policies(api):
    """PRD §3.1: "An `aoc_number` — the Air Operator Certificate reference — is
    optional in general and defaults to null, but it is mandatory whenever
    `operator_type` is `AIR_CARRIER`; supplying it when the operator is not an air
    carrier is permitted, and when it is supplied it must be between 4 and 16
    characters drawn from uppercase letters, digits and the hyphen."

    Design: Corner/entities/corner_operator_creation_returns_every_declared_field
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    payload = f.operator_payload()
    assert "aoc_number" not in payload, "the certificate reference must be omitted here"

    operator = validate_unpaginated(
        api.create_operator(payload, headers=users.UNDERWRITER), expected_status=201
    )

    assert operator["aoc_number"] is None
    assert operator["policy_count"] == 0

    read_back = fx.fetch_operator(api, operator["id"])
    assert read_back["aoc_number"] is None
    assert read_back["policy_count"] == 0


# ----------------------------------------------------------------------
# Airframes
# ----------------------------------------------------------------------
def test_an_airframe_read_reports_its_terms_and_depreciation_at_the_clock_year(api):
    """PRD §3.1: "For the value reported on a read, the reference year is the calendar
    year of the current logical clock."

    Design: Corner/entities/corner_aircraft_retrieval_returns_stored_plus_clock_basis_depreciation
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    payload = f.aircraft_payload()
    created = validate_unpaginated(
        api.create_aircraft(payload, headers=users.UNDERWRITER), expected_status=201
    )

    response = api.get_aircraft(created["id"], headers=users.UNDERWRITER)
    aircraft = validate_unpaginated(response)

    assert_request_meta(response)
    assert_aircraft_shape(aircraft)
    assert_fields_present(aircraft, a.AIRCRAFT_FIELDS)
    assert aircraft["id"] == created["id"]
    assert_field_values(
        aircraft,
        registration_mark=payload["registration_mark"],
        aircraft_class=payload["aircraft_class"],
        manufacture_year=payload["manufacture_year"],
        hull_new_value_cents=payload["hull_new_value_cents"],
        seat_count=payload["seat_count"],
        max_takeoff_weight_kg=payload["max_takeoff_weight_kg"],
    )
    assert aircraft["current_depreciated_value_cents"] == c.depreciated_value_cents(
        payload["hull_new_value_cents"],
        payload["manufacture_year"],
        c.calendar_year_of(f.CLOCK_BEFORE_INCEPTION),
    )


# ----------------------------------------------------------------------
# Collection reads
# ----------------------------------------------------------------------
def test_the_policy_list_reports_the_filtered_total_and_the_page_window(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the page window is
    applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/corner_policies_list_returns_pagination_envelope_with_filter
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    first = fx.make_policy(api, operator["id"], policy_type=PolicyType.SINGLE_AIRCRAFT)
    second = fx.make_policy(
        api,
        operator["id"],
        policy_type=PolicyType.SINGLE_AIRCRAFT,
        territorial_limit_code=TerritorialLimit.CONTINENTAL,
    )
    fleet = fx.make_policy(api, operator["id"], policy_type=PolicyType.FLEET)
    all_ids = {first["id"], second["id"], fleet["id"]}

    page_one, meta_one = validate_list(
        api.list_policies(
            headers=users.UNDERWRITER,
            params={"status": PolicyStatus.DRAFT, "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert_ordered_by_created_at(page_one)

    page_two, meta_two = validate_list(
        api.list_policies(
            headers=users.UNDERWRITER,
            params={"status": PolicyStatus.DRAFT, "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    windowed_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(windowed_ids)) == 3, "the two pages must not repeat a row"
    assert set(windowed_ids) == all_ids

    fleet_rows, fleet_meta = validate_list(
        api.list_policies(
            headers=users.UNDERWRITER, params={"policy_type": PolicyType.FLEET}
        )
    )
    assert [row["id"] for row in fleet_rows] == [fleet["id"]]
    assert fleet_meta["limit"] == c.DEFAULT_LIMIT
    assert fleet_meta["offset"] == c.DEFAULT_OFFSET
    assert fleet_meta["total_count"] == 1
    assert fleet_meta["has_more"] is False


@pytest.mark.parametrize(
    "read_one, expected_error",
    [
        (
            lambda client: client.get_policy(
                NON_EXISTENT_UUID, headers=users.UNDERWRITER
            ),
            ApiErrorId.POLICY_NOT_FOUND,
        ),
        (
            lambda client: client.get_claim(
                NON_EXISTENT_UUID, headers=users.UNDERWRITER
            ),
            ApiErrorId.CLAIM_NOT_FOUND,
        ),
    ],
    ids=["policy", "claim"],
)
def test_a_well_formed_unknown_path_id_reports_that_collections_not_found_code(
    api, read_one, expected_error
):
    """PRD §2.11: "The `{id}` in the path resolves in the endpoint's own collection —
    the matching not-found code from §2.7, 404."

    Design: Corner/entities/corner_policy_not_found_on_well_formed_unknown_uuid
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)

    response = read_one(api)

    validate_error(response, expected_error)
    assert_request_meta(response)


# ----------------------------------------------------------------------
# Request-body shape
# ----------------------------------------------------------------------
def test_a_hull_body_missing_or_mistyping_a_field_is_an_invalid_request(api):
    """PRD §2.11: "Every input field that has no default is present, and every present
    field carries its declared JSON type: integers are JSON numbers with no fractional
    part, instants are RFC-3339 UTC strings ending in `Z`, and booleans are JSON
    booleans — `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/corner_schedule_creation_missing_required_field_returns_invalid_request
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])

    omitted = f.schedule_payload(
        policy["id"], book["aircraft_id"], book["pilot_id"]
    )
    omitted.pop("agreed_value_cents")
    validate_error(
        api.create_schedule(omitted, headers=users.UNDERWRITER),
        ApiErrorId.INVALID_REQUEST,
    )

    mistyped = f.schedule_payload(
        policy["id"],
        book["aircraft_id"],
        book["pilot_id"],
        agreed_value_cents="45000000",
    )
    validate_error(
        api.create_schedule(mistyped, headers=users.UNDERWRITER),
        ApiErrorId.INVALID_REQUEST,
    )

    rows, meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER, params={"policy_id": policy["id"]}
        )
    )
    assert rows == [], "a rejected body must not leave a hull on the policy"
    assert meta["total_count"] == 0
    assert fx.fetch_policy(api, policy["id"])["live_schedule_count"] == 0


# ----------------------------------------------------------------------
# Declared defaults
# ----------------------------------------------------------------------
def test_a_policy_opened_on_its_mandatory_terms_alone_takes_the_declared_defaults(api):
    """PRD §3.3: "`permitted_use_classes` is the set of use classifications the policy
    is allowed to schedule; it defaults to all four — `PRIVATE`, `BUSINESS`,
    `INSTRUCTIONAL` and `COMMERCIAL` — and when supplied must be a non-empty subset of
    those four."

    Design: Corner/entities/corner_optional_field_defaults_applied_on_omission
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    payload = f.minimal_policy_payload(operator["id"])
    for optional in (
        "permitted_use_classes",
        "automatic_acquisition_enabled",
        "acquisition_reporting_days",
        "war_risk_required",
    ):
        assert optional not in payload, f"{optional} must be omitted here"

    policy = validate_unpaginated(
        api.create_policy(payload, headers=users.UNDERWRITER), expected_status=201
    )

    assert_policy_shape(policy)
    assert len(policy["permitted_use_classes"]) == 4
    assert set(policy["permitted_use_classes"]) == set(
        c.DEFAULT_PERMITTED_USE_CLASSES
    )
    assert_field_values(
        policy,
        automatic_acquisition_enabled=False,
        acquisition_reporting_days=c.ACQUISITION_REPORTING_DAYS_DEFAULT,
        war_risk_required=False,
        premises_liability_extension=False,
        product_liability_extension=False,
    )


def test_omitted_optional_inputs_default_on_a_pilot_and_on_a_hull(api):
    """PRD §3.4: "An `acquisition_source` may be supplied and defaults to `SCHEDULED`;
    the alternative is `AUTOMATIC_ACQUISITION`, described in §3.8."

    Design: Corner/entities/corner_optional_field_defaults_applied_on_omission
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    aircraft = fx.make_aircraft(api)

    pilot_body = f.senior_pilot_payload()
    pilot_body.pop("instrument_rated")
    pilot = validate_unpaginated(
        api.create_pilot(pilot_body, headers=users.UNDERWRITER), expected_status=201
    )
    assert_pilot_shape(pilot)
    assert pilot["instrument_rated"] is False
    expected_score = c.qualification_score(
        pilot_body["total_logged_hours"],
        pilot_body["hours_on_type"],
        False,
        pilot_body["license_type"],
        pilot_body["last_training_completed_at"],
        f.CLOCK_BEFORE_INCEPTION,
    )
    assert pilot["qualification_score_logged"] == expected_score
    assert pilot["rating_band_logged"] == c.band_for_score(expected_score)

    policy = fx.make_policy(api, operator["id"])
    hull_body = f.schedule_payload(policy["id"], aircraft["id"], pilot["id"])
    hull_body.pop("acquisition_source")

    schedule = validate_unpaginated(
        api.create_schedule(hull_body, headers=users.UNDERWRITER), expected_status=201
    )

    assert_schedule_shape(schedule)
    assert_field_values(
        schedule,
        acquisition_source=AcquisitionSource.SCHEDULED,
        coverage_status=CoverageStatus.PENDING,
        warranty_status=WarrantyStatus.PENDING_EVIDENCE,
        warranty_basis=WarrantyBasis.LOGGED_HOURS,
    )
    assert schedule["reported_declaration_id"] is None


# ----------------------------------------------------------------------
# Server-owned fields
# ----------------------------------------------------------------------
def test_a_pilots_score_and_audit_fields_ignore_what_the_client_sends(api):
    """PRD §3.1: "All three audit fields — `verified_total_hours`,
    `verified_hours_on_type` and `verified_at` — start as null, and remain null until a
    logbook audit is recorded as described in §3.2."

    Design: Corner/entities/corner_computed_fields_with_client_supplied_input_ignored
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    payload = f.pilot_payload(
        qualification_score_logged=999,
        rating_band_logged=PilotBand.BAND_A,
        verified_total_hours=5000,
        verified_hours_on_type=4000,
    )

    pilot = validate_unpaginated(
        api.create_pilot(payload, headers=users.UNDERWRITER), expected_status=201
    )

    assert_pilot_shape(pilot)
    expected_score = c.qualification_score(
        payload["total_logged_hours"],
        payload["hours_on_type"],
        payload["instrument_rated"],
        payload["license_type"],
        payload["last_training_completed_at"],
        f.CLOCK_BEFORE_INCEPTION,
    )
    assert pilot["qualification_score_logged"] == expected_score
    assert pilot["rating_band_logged"] == c.band_for_score(expected_score)
    assert pilot["verified_total_hours"] is None
    assert pilot["verified_hours_on_type"] is None
    assert pilot["verified_at"] is None
    assert pilot["qualification_score_verified"] is None
    assert pilot["rating_band_verified"] is None

    read_back = fx.fetch_pilot(api, pilot["id"])
    assert read_back["qualification_score_logged"] == expected_score
    assert read_back["verified_at"] is None


def test_a_hulls_rate_and_premium_are_derived_rather_than_accepted(api):
    """PRD §3.4: "The gross annual premium is `agreed_value_cents` multiplied by
    `rate_ppm`, divided by 1,000,000, with the fraction discarded."

    Design: Corner/entities/corner_computed_fields_with_client_supplied_input_ignored
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])
    payload = f.schedule_payload(
        policy["id"],
        book["aircraft_id"],
        book["pilot_id"],
        rate_ppm=1,
        hull_premium_cents=1,
        rated_pilot_band=PilotBand.BAND_A,
        coverage_status=CoverageStatus.ACTIVE,
        warranted_min_total_hours=1,
        warranted_min_hours_on_type=1,
    )

    schedule = validate_unpaginated(
        api.create_schedule(payload, headers=users.UNDERWRITER), expected_status=201
    )

    assert_schedule_shape(schedule)
    expected_band = book["pilot"]["rating_band_logged"]
    expected_rate = c.rate_ppm_for(
        policy["base_hull_rate_ppm"],
        payload["use_class"],
        policy["territorial_limit_code"],
        expected_band,
    )
    expected_premium = c.annual_premium_cents(
        payload["agreed_value_cents"],
        expected_rate,
        policy_type=policy["policy_type"],
        live_schedule_count=1,
    )
    assert_field_values(
        schedule,
        rated_pilot_band=expected_band,
        rate_ppm=expected_rate,
        hull_premium_cents=expected_premium,
        coverage_status=CoverageStatus.PENDING,
        warranted_min_total_hours=c.WARRANTY_MIN_TOTAL_HOURS[payload["use_class"]],
        warranted_min_hours_on_type=c.WARRANTY_MIN_ON_TYPE_HOURS[payload["use_class"]],
    )


def test_the_server_mints_the_policy_number_state_and_money_figures_itself(api):
    """PRD §3.3: "`policy_number` is a sequential human reference formed from the prefix
    `AVN-` followed by a six-digit zero-padded counter, allocated in policy creation
    order by `created_at` ascending and starting at `AVN-000001`."

    Design: Corner/entities/corner_system_fields_server_minted_with_client_input_ignored
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    payload = f.policy_payload(
        operator["id"],
        policy_number="AVN-999999",
        status=PolicyStatus.BOUND,
        term_days=1,
        written_premium_cents=999999,
        total_hull_sum_insured_cents=123,
        live_schedule_count=7,
    )

    policy = validate_unpaginated(
        api.create_policy(payload, headers=users.UNDERWRITER), expected_status=201
    )

    assert_policy_shape(policy)
    assert_policy_number_format(policy["policy_number"])
    assert policy["policy_number"] == c.FIRST_POLICY_NUMBER
    assert_field_values(
        policy,
        status=PolicyStatus.DRAFT,
        term_days=c.whole_days_between(
            payload["effective_from"], payload["effective_to"]
        ),
        total_hull_sum_insured_cents=0,
        written_premium_cents=0,
        outstanding_reserve_cents=0,
        paid_hull_cents=0,
        live_schedule_count=0,
    )
    assert_instants_equal(policy["effective_from"], payload["effective_from"])
    assert_instants_equal(policy["effective_to"], payload["effective_to"])
    assert fx.fetch_operator(api, operator["id"])["policy_count"] == 1


# ----------------------------------------------------------------------
# Declared constraints
# ----------------------------------------------------------------------
def test_unknown_enum_members_and_out_of_range_integers_fail_validation(api):
    """PRD §2.11: "Every supplied value satisfies its declared constraint: enum
    membership, string length and character set, integer sign and range, and the
    ordering rules that `effective_from` precede `effective_to`, that `period_from` be
    at or before `period_to`, and that `coverage_from` precede `coverage_to` —
    `ERR_VALIDATION_FAILED`, 422."

    Design: Corner/entities/corner_enum_and_range_constraints_rejected_with_validation_failed
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    mark = f.unique_registration_mark()

    rejected = [
        api.create_aircraft(
            f.aircraft_payload(registration_mark=mark, aircraft_class="GLIDER"),
            headers=users.UNDERWRITER,
        ),
        api.create_aircraft(
            f.aircraft_payload(
                registration_mark=mark,
                manufacture_year=c.MANUFACTURE_YEAR_MIN - 1,
            ),
            headers=users.UNDERWRITER,
        ),
        api.create_policy(
            f.policy_payload(
                operator["id"], base_hull_rate_ppm=c.BASE_HULL_RATE_PPM_MIN - 1
            ),
            headers=users.UNDERWRITER,
        ),
        api.create_policy(
            f.policy_payload(
                operator["id"],
                effective_from=f.POLICY_EFFECTIVE_TO,
                effective_to=f.POLICY_EFFECTIVE_FROM,
            ),
            headers=users.UNDERWRITER,
        ),
    ]
    for response in rejected:
        validate_error(response, ApiErrorId.VALIDATION_FAILED)

    rows, meta = validate_list(api.list_policies(headers=users.UNDERWRITER))
    assert rows == [], "a rejected policy body must not open a policy"
    assert meta["total_count"] == 0

    survivor = validate_unpaginated(
        api.create_aircraft(
            f.aircraft_payload(registration_mark=mark), headers=users.UNDERWRITER
        ),
        expected_status=201,
    )
    assert survivor["registration_mark"] == mark
    assert survivor["aircraft_class"] == AircraftClass.MULTI_PISTON


# ----------------------------------------------------------------------
# Immutable resources
# ----------------------------------------------------------------------
def _claim_under_investigation(api):
    """A bound worldwide fleet policy with one instructional hull and an open claim."""
    book = fx.bound_policy_with_hull(api)
    fx.advance_clock(api, f.CLOCK_LATE_TERM)
    claim = fx.make_claim(
        api, book["policy_id"], book["schedule_id"], loss_date=f.CLOCK_AFTER_LOSS
    )
    book["claim"] = fx.investigate_claim(api, claim["id"])
    book["claim_id"] = claim["id"]
    return book


def test_a_damage_assessment_is_written_without_a_version_or_an_updated_at(api):
    """PRD §2.4: "Two resources are immutable once written and therefore carry neither
    `updated_at` nor `version`: `DamageAssessment` and `PremiumTransaction`."

    Design: Corner/entities/corner_immutable_entities_carry_no_version_and_no_write_endpoint
    """
    book = _claim_under_investigation(api)
    payload = f.damage_assessment_payload(
        book["claim_id"],
        repair_cost_estimate_cents=20000000,
        assessed_at="2026-10-20T00:00:00Z",
    )

    response = api.create_damage_assessment(payload, headers=users.CLAIMS_ADJUSTER)
    assessment = validate_unpaginated(response, expected_status=201)

    assert_damage_assessment_shape(assessment)
    assert_immutable_common_fields(assessment)
    expected_ratio = c.ctl_ratio_ppm(
        payload["repair_cost_estimate_cents"],
        book["schedule"]["agreed_value_cents"],
    )
    assert expected_ratio < c.CTL_THRESHOLD_PPM
    assert_field_values(
        assessment,
        claim_id=book["claim_id"],
        repair_cost_estimate_cents=payload["repair_cost_estimate_cents"],
        assessor_reference=payload["assessor_reference"],
        ctl_ratio_ppm=expected_ratio,
        verdict=AssessmentVerdict.REPAIRABLE,
    )
    assert_instants_equal(assessment["assessed_at"], payload["assessed_at"])

    read_back = fx.fetch_damage_assessment(api, assessment["id"])
    assert_immutable_common_fields(read_back)
    assert read_back["ctl_ratio_ppm"] == expected_ratio

    claim = fx.fetch_claim(api, book["claim_id"])
    assert_claim_shape(claim)
    assert_field_values(
        claim,
        assessment_count=1,
        ctl_ratio_ppm=expected_ratio,
        ctl_flag=False,
        loss_type=LossType.HULL_DAMAGE,
    )


def test_a_premium_ledger_row_is_written_without_a_version_or_an_updated_at(api):
    """PRD §2.4: "There is no operation anywhere in this API that alters an existing
    damage assessment or an existing ledger row; corrections are made by appending new
    rows, never by editing old ones."

    Design: Corner/entities/corner_immutable_entities_carry_no_version_and_no_write_endpoint
    """
    book = fx.bound_policy_with_hull(api)
    policy = book["policy"]
    expected_rate = c.rate_ppm_for(
        policy["base_hull_rate_ppm"],
        UseClass.INSTRUCTIONAL,
        policy["territorial_limit_code"],
        book["pilot"]["rating_band_logged"],
    )
    expected_premium = c.annual_premium_cents(
        book["schedule"]["agreed_value_cents"],
        expected_rate,
        policy_type=policy["policy_type"],
        live_schedule_count=1,
    )

    rows, meta = validate_list(
        api.list_premium_transactions(
            headers=users.UNDERWRITER, params={"policy_id": book["policy_id"]}
        )
    )

    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert_premium_transaction_shape(rows[0])
    assert_immutable_common_fields(rows[0])
    assert_ledger_row(
        rows[0],
        txn_type=TxnType.INITIAL_PREMIUM,
        amount_cents=expected_premium,
        basis=TxnBasis.ANNUAL,
        effective_date=policy["effective_from"],
        policy_id=book["policy_id"],
    )
    assert rows[0]["endorsement_id"] is None

    single = validate_unpaginated(
        api.get_premium_transaction(rows[0]["id"], headers=users.UNDERWRITER)
    )
    assert_immutable_common_fields(single)
    assert single["amount_cents"] == expected_premium


# ----------------------------------------------------------------------
# Reference integrity
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "reference, expected_error",
    [
        ("aircraft_id", ApiErrorId.AIRCRAFT_NOT_FOUND),
        ("named_pilot_id", ApiErrorId.PILOT_NOT_FOUND),
        ("policy_id", ApiErrorId.POLICY_NOT_FOUND),
    ],
)
def test_a_hull_body_naming_an_unknown_parent_reports_that_collections_code(
    api, reference, expected_error
):
    """PRD §2.11: "Every foreign key in the request body resolves, in the declared
    body-field order — the matching not-found code, 404."

    Design: Corner/entities/corner_foreign_key_targets_must_exist_on_create
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])
    payload = f.schedule_payload(
        policy["id"], book["aircraft_id"], book["pilot_id"]
    )
    payload[reference] = NON_EXISTENT_UUID

    validate_error(
        api.create_schedule(payload, headers=users.UNDERWRITER), expected_error
    )

    rows, meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER, params={"policy_id": policy["id"]}
        )
    )
    assert rows == [], "an unresolvable reference must not attach a hull"
    assert meta["total_count"] == 0


def test_the_first_unresolvable_body_reference_in_the_declared_order_decides(api):
    """PRD §2.7: "The first unresolvable reference in that order decides the error, so a
    request naming both a non-existent policy and a non-existent aircraft reports
    `ERR_POLICY_NOT_FOUND` rather than `ERR_AIRCRAFT_NOT_FOUND`."

    Design: Corner/entities/corner_foreign_key_targets_must_exist_on_create
    """
    book = fx.registered_book(api)
    payload = f.schedule_payload(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, book["pilot_id"]
    )

    validate_error(
        api.create_schedule(payload, headers=users.UNDERWRITER),
        ApiErrorId.POLICY_NOT_FOUND,
    )


def test_a_claim_must_name_a_hull_that_belongs_to_the_policy_it_names(api):
    """PRD §2.7: "A reference that exists but belongs to the wrong policy is refused
    with `ERR_SCHEDULE_POLICY_MISMATCH` (HTTP 409)."

    Design: Corner/entities/corner_cross_reference_integrity_schedule_must_belong_to_named_policy
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    pilot = fx.make_pilot(api, f.senior_pilot_payload())
    own_frame = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(f.unique_registration_mark())
    )
    other_frame = fx.make_aircraft(
        api, f.single_piston_aircraft_payload(f.unique_registration_mark())
    )

    own_policy = fx.make_policy(
        api,
        operator["id"],
        policy_type=PolicyType.SINGLE_AIRCRAFT,
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )
    own_hull = fx.make_schedule(
        api,
        own_policy["id"],
        own_frame["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=30000000,
    )
    other_policy = fx.make_policy(
        api,
        operator["id"],
        policy_type=PolicyType.SINGLE_AIRCRAFT,
        permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
    )
    other_hull = fx.make_schedule(
        api,
        other_policy["id"],
        other_frame["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=30000000,
    )
    fx.bind_policy(api, own_policy["id"])
    fx.bind_policy(api, other_policy["id"])
    fx.advance_clock(api, f.CLOCK_LATE_TERM)

    mismatched = f.claim_payload(
        own_policy["id"], other_hull["id"], loss_date=f.CLOCK_AFTER_LOSS
    )
    validate_error(
        api.create_claim(mismatched, headers=users.CLAIMS_ADJUSTER),
        ApiErrorId.SCHEDULE_POLICY_MISMATCH,
    )
    assert fx.claims_of_policy(api, own_policy["id"]) == []
    assert fx.claims_of_policy(api, other_policy["id"]) == []

    coherent = f.claim_payload(
        own_policy["id"], own_hull["id"], loss_date=f.CLOCK_AFTER_LOSS
    )
    claim = validate_unpaginated(
        api.create_claim(coherent, headers=users.CLAIMS_ADJUSTER), expected_status=201
    )

    assert_claim_shape(claim)
    assert claim["policy_id"] == own_policy["id"]
    assert claim["schedule_id"] == own_hull["id"]
    assert_instants_equal(claim["loss_date"], f.CLOCK_AFTER_LOSS)
