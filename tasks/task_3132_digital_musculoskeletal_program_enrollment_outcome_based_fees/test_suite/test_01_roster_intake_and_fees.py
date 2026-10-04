"""Roster intake, screening, member rows and the two roster-fee readings.

Covers the client contract, care-track configuration, roster ingestion and its
guards, the musculoskeletal screening rule, the member row's computed and
system fields, and the two divergent roster-fee variants.
"""
import re

import pytest

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_client_payload,
    create_eligibility_file_payload,
    create_member_payload,
    create_program_track_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
    CLINICAL_OPS,
    ENROLLMENT_OPS,
    BILLING_OPS,
    setup_client,
    setup_roster,
    setup_scenario,
    setup_tracks,
    assign_tracks,
    record_measurement,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

THREE_MEMBER_ROSTER = [
    {"external_member_ref": "NW-0001", "full_name": "Ana Ruiz",
     "date_of_birth": "1985-04-12T00:00:00Z", "musculo_condition_code": "KNEE_OA",
     "baseline_pain_score": 7.5, "baseline_function_score": 45.0,
     "red_flag_multipliers": [1.15]},
    {"external_member_ref": "NW-0002", "full_name": "Ben Okafor",
     "date_of_birth": "1979-11-02T00:00:00Z", "musculo_condition_code": "LOW_BACK",
     "baseline_pain_score": 6.0, "baseline_function_score": 55.0,
     "red_flag_multipliers": [1.15, 1.15]},
    {"external_member_ref": "NW-0003", "full_name": "Cleo Marsh",
     "date_of_birth": "1990-06-30T00:00:00Z", "musculo_condition_code": "OTHER",
     "baseline_pain_score": 1.0, "baseline_function_score": 90.0,
     "red_flag_multipliers": []},
]


# ══════════════════════════════════════════════════════════════════
# Client contract and care-track configuration
# ══════════════════════════════════════════════════════════════════

def test_client_create_returns_every_declared_field_and_starts_active(api, clinical_ops_headers):
    """PRD §3.1: "A freshly created account is `ACTIVE`; the only other states it
    can hold are `SUSPENDED` and `CLOSED`".
    PRD §3.1: "`billing_model` selects between `ENGAGEMENT_MILESTONE` and
    `OUTCOME_SHARED_SAVINGS` and defaults to `ENGAGEMENT_MILESTONE` when the
    operator does not specify one."
    PRD §3.1: "it defaults to 0.30 and must lie between 0 and 1 inclusive."
    PRD §3.1: "it defaults to 0.60 and must likewise lie between 0 and 1 inclusive."

    Design: Corner/entities/client_create_returns_every_declared_field_and_starts_active
    """
    response = api.create_client(
        {"legal_name": "Halewood Utilities", "client_type": "HEALTH_PLAN"},
        clinical_ops_headers,
    )
    data = validate_success(response, expected_status=201)

    assert data["legal_name"] == "Halewood Utilities"
    assert data["client_type"] == "HEALTH_PLAN"
    assert data["account_status"] == "ACTIVE", "a freshly created account is ACTIVE"
    assert data["billing_model"] == "ENGAGEMENT_MILESTONE", (
        "billing_model defaults to ENGAGEMENT_MILESTONE when unspecified"
    )
    assert data["expected_monthly_engagement_rate"] == pytest.approx(0.60, abs=1e-9)
    assert data["savings_share_rate"] == pytest.approx(0.30, abs=1e-9)
    assert data["version"] == 1, "version starts at 1 on creation"

    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert response.json()["meta"]["api_request_id"].startswith("req_")


def test_program_track_defaults_min_adherence_rate_to_seventy_percent(api, clinical_ops_headers):
    """PRD §3.1: "a `min_adherence_rate` that a member must hold to stay
    engagement-milestone eligible (defaulting to 0.70)".
    PRD §3.1: "The weights map carries exactly two keys, `LOW` and `HIGH`, and no others."

    Design: Corner/entities/program_track_defaults_min_adherence_rate_to_seventy_percent
    """
    payload = create_program_track_payload(track_code="CHRONIC", base_fee_per_member_cents=12000)
    payload.pop("min_adherence_rate")

    data = validate_success(
        api.create_program_track(payload, clinical_ops_headers), expected_status=201)

    assert data["min_adherence_rate"] == pytest.approx(0.70, abs=1e-9), (
        "omitting the rate leaves the declared 0.70 default in force"
    )
    assert data["track_code"] == "CHRONIC"
    assert data["severity_weights"] == {"LOW": 0.2, "HIGH": 0.5}


def test_program_track_carries_only_identity_and_created_at(api, clinical_ops_headers):
    """PRD §2.5: "Two configuration entities are deliberately narrower.
    `ProgramTrack` and `Clinician` carry only `id` and `created_at`; neither
    carries `updated_at`, and neither carries `version`."
    PRD §2.5: "no request anywhere in this API carries an expected-version field
    for either of them".

    Design: Corner/entities/program_track_carries_only_identity_and_created_at
    """
    created = validate_success(
        api.create_program_track(create_program_track_payload(), clinical_ops_headers),
        expected_status=201)

    read_one = validate_success(api.get_program_track(created["id"], clinical_ops_headers))
    read_two = validate_success(api.get_program_track(created["id"], clinical_ops_headers))

    assert is_valid_uuid(read_one["id"])
    assert is_iso8601_timestamp(read_one["created_at"])
    assert "version" not in read_one, "a care-track configuration is not version-guarded"
    assert "updated_at" not in read_one, "a care-track configuration carries no updated_at"

    assert read_one["min_adherence_rate"] == read_two["min_adherence_rate"]
    assert read_one["base_fee_per_member_cents"] == read_two["base_fee_per_member_cents"] == 9000


# ══════════════════════════════════════════════════════════════════
# Member rows
# ══════════════════════════════════════════════════════════════════

def test_member_get_round_trips_roster_screening_fields(api, clinical_ops_headers,
                                                        enrollment_ops_headers):
    """PRD §3.1: "Each row carries the sponsoring `client_account_id`, the owning
    `eligibility_file_id`, the client-side `external_member_ref` — which must be
    unique within that client — the member's `full_name`, a `date_of_birth`
    expressed as an ISO 8601 date at midnight UTC, a `musculo_condition_code` from
    the set `KNEE_OA`, `LOW_BACK`, `SHOULDER`, `HIP`, `NECK` or `OTHER`, a
    `baseline_pain_score` between 0 and 10 inclusive, a `baseline_function_score`
    between 0 and 100 inclusive, and an optional `red_flag_multipliers` list that
    defaults to the empty list."
    PRD §3.1: "A new member row is `PENDING_ELIGIBILITY` and carries no
    eligibility basis yet".

    Design: Corner/entities/member_get_round_trips_roster_screening_fields
    """
    client = setup_client()
    file_obj = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client["id"]), enrollment_ops_headers))

    created = validate_success(api.create_member(
        create_member_payload(
            client["id"], file_obj["id"],
            external_member_ref="HW-0001", full_name="Ilse Marchetti",
            date_of_birth="1977-05-23T00:00:00Z", musculo_condition_code="SHOULDER",
            baseline_pain_score=6.5, baseline_function_score=51.5,
            red_flag_multipliers=[1.25, 1.10],
        ),
        enrollment_ops_headers,
    ), expected_status=201)

    fetched = validate_success(api.get_member(created["id"], enrollment_ops_headers))

    assert fetched["musculo_condition_code"] == "SHOULDER"
    assert fetched["external_member_ref"] == "HW-0001"
    assert fetched["baseline_pain_score"] == pytest.approx(6.5, abs=1e-9)
    assert fetched["baseline_function_score"] == pytest.approx(51.5, abs=1e-9)
    assert fetched["red_flag_multipliers"] == [1.25, 1.10], (
        "the multipliers array round-trips unchanged"
    )
    assert fetched["member_status"] == "PENDING_ELIGIBILITY"


def test_member_get_unknown_id_returns_resource_not_found(api, enrollment_ops_headers):
    """PRD §5: "`ERR_RESOURCE_NOT_FOUND` | 404 Not Found". PRD §2.9: "the leftmost
    unknown segment determines the failure and the response is the 404 carrying
    `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/member_get_unknown_id_returns_resource_not_found
    """
    response = api.get_member("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", enrollment_ops_headers)

    error = validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)

    assert response.json()["response_type"] == "error"
    assert error["message"].strip(), "the error envelope carries a non-empty message"


def test_member_create_missing_condition_code_returns_error_envelope(api, clinical_ops_headers,
                                                                   enrollment_ops_headers):
    """PRD §3.1: "Each row carries the sponsoring `client_account_id`, the owning
    `eligibility_file_id`, the client-side `external_member_ref` — which must be
    unique within that client — the member's `full_name`, a `date_of_birth`
    expressed as an ISO 8601 date at midnight UTC, a `musculo_condition_code` from
    the set `KNEE_OA`, `LOW_BACK`, `SHOULDER`, `HIP`, `NECK` or `OTHER`, a
    `baseline_pain_score` between 0 and 10 inclusive, a `baseline_function_score`
    between 0 and 100 inclusive, and an optional `red_flag_multipliers` list that
    defaults to the empty list."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error." PRD §2.2: "The `response_type` is either \"object\" for a
    single resource or \"array\" for a list of resources."

    Design: Corner/entities/member_create_missing_condition_code_returns_invalid_request
    """
    client = setup_client()
    file_obj = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client["id"]), enrollment_ops_headers))

    payload = create_member_payload(
        client["id"], file_obj["id"], external_member_ref="HW-0005",
        full_name="Nils Ohlsson", date_of_birth="1980-03-03T00:00:00Z",
        baseline_pain_score=5.0, baseline_function_score=60.0,
    )
    payload.pop("musculo_condition_code")

    refused = api.create_member(payload, enrollment_ops_headers)
    body = refused.json()

    assert refused.status_code >= 400, "a row with no condition code is refused"
    assert body["response_type"] == "error", (
        "the omission is reported through the error envelope, not as a created Member"
    )
    assert isinstance(body["data"]["error_id"], str) and body["data"]["error_id"]

    rows = get_success_data(api.list_members(
        enrollment_ops_headers, {"eligibility_file_id": file_obj["id"]}))
    assert rows == [], "nothing was written"

    accepted = api.create_member(
        {**payload, "musculo_condition_code": "KNEE_OA"}, enrollment_ops_headers)
    assert accepted.status_code == 201, "the omission was the only blocker"


def test_member_system_fields_are_server_stamped_and_versioned(api, clinical_ops_headers,
                                                               enrollment_ops_headers):
    """PRD §2.5: "The `id` is a server-minted UUID with no type prefix: it is never
    `mem_…`, `enr_…` or any other domain-flavoured string, and clients must treat
    it as an opaque token."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of that resource".
    PRD §2.5: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    rendered with three fractional digits."

    Design: Corner/entities/member_system_fields_are_server_stamped_and_versioned
    """
    client = setup_client()
    file_obj = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client["id"]), enrollment_ops_headers))

    created = validate_success(api.create_member(
        create_member_payload(
            client["id"], file_obj["id"], external_member_ref="HW-0007",
            full_name="Petra Nowak", date_of_birth="1983-08-08T00:00:00Z",
            musculo_condition_code="KNEE_OA", baseline_pain_score=6.0,
            baseline_function_score=54.0,
        ),
        enrollment_ops_headers,
    ), expected_status=201)

    assert UUID_RE.match(created["id"]), "id is a bare UUID with no type prefix"
    assert created["version"] == 1
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", created["created_at"]), (
        "timestamps carry three fractional digits"
    )
    assert created["created_at"] == created["updated_at"], (
        "nothing has mutated the row yet at creation"
    )

    get_success_data(api.screen_eligibility_file(file_obj["id"], enrollment_ops_headers))
    advanced = get_success_data(api.get_member(created["id"], enrollment_ops_headers))
    assert advanced["version"] == 2, "screening mutates the row and advances its version"


# ══════════════════════════════════════════════════════════════════
# Screening and its outcome counts
# ══════════════════════════════════════════════════════════════════

def test_screening_succeeds_when_every_condition_is_satisfied(api, clinical_ops_headers,
                                                              enrollment_ops_headers):
    """PRD §3.1: "An `EnrollmentOps` operator screens a file, which requires the
    file to be `INGESTED` and to carry at least one member row."
    PRD §3.1: "`eligible_member_count` and `ineligible_member_count` count the
    members that landed in each outcome and `screened_member_count` is their sum".
    PRD §3.1: "A row becomes `ELIGIBLE` when the member carries at least one roster
    row whose `musculo_condition_code` is not `OTHER` and whose `date_of_birth` is
    at least 18 years before the current logical clock instant; that outcome
    records `eligibility_basis` as `MSK_FLAG`."

    Design: Corner/validations/screening_succeeds_when_every_condition_is_satisfied
    """
    client = setup_client(legal_name="Halewood Utilities")
    setup_tracks(acute_fee=9000)
    roster = setup_roster(client["id"], [
        {"external_member_ref": "HW-0017", "full_name": "Aldo Ferretti",
         "date_of_birth": "1980-05-05T00:00:00Z", "musculo_condition_code": "KNEE_OA",
         "baseline_pain_score": 6.5, "baseline_function_score": 53.0},
    ], screen=False)

    file_id = roster["file"]["id"]
    assert roster["file"]["file_status"] == "INGESTED"
    version_before = roster["file"]["version"]

    data = validate_success(api.screen_eligibility_file(file_id, enrollment_ops_headers))

    assert data["file_status"] == "SCREENED"
    assert data["screened_member_count"] == 1
    assert data["eligible_member_count"] == 1
    assert data["ineligible_member_count"] == 0
    assert data["total_monthly_fee_cents"] == 900000, (
        "9000 * 100 * 1.0 over the single eligible member"
    )
    assert data["version"] == version_before + 1, "the file's version advanced by exactly 1"

    member = get_success_data(api.get_member(roster["members"][0]["id"], enrollment_ops_headers))
    assert member["member_status"] == "ELIGIBLE"
    assert member["eligibility_basis"] == "MSK_FLAG"


def test_roster_fee_eligible_count_excludes_condition_free_members(api, clinical_ops_headers,
                                                                   enrollment_ops_headers):
    """PRD §3.2: "Its inclusion set is every member row on the file, in roster row
    order, so ineligible members contribute their half weight to the numerator
    while only the eligible ones form the denominator."
    PRD §3.1: "A row becomes `INELIGIBLE` when the member carries no row whose
    `musculo_condition_code` is not `OTHER`; that outcome records
    `eligibility_basis` as `NO_MSK_FLAG`."

    Design: Corner/calculations/roster_fee_eligible_count_excludes_condition_free_members
    """
    client = setup_client(legal_name="Halewood Utilities")
    setup_tracks(acute_fee=9000)
    roster = setup_roster(client["id"], [
        {"external_member_ref": "HW-0013", "full_name": "Wanda Ilves",
         "date_of_birth": "1981-03-03T00:00:00Z", "musculo_condition_code": "KNEE_OA",
         "baseline_pain_score": 6.5, "baseline_function_score": 52.0},
        {"external_member_ref": "HW-0014", "full_name": "Xenia Boas",
         "date_of_birth": "1986-06-06T00:00:00Z", "musculo_condition_code": "OTHER",
         "baseline_pain_score": 1.0, "baseline_function_score": 92.0},
    ])

    file_obj = roster["file"]
    assert file_obj["eligible_member_count"] == 1
    assert file_obj["ineligible_member_count"] == 1

    eligible_member = get_success_data(api.get_member(roster["members"][0]["id"], enrollment_ops_headers))
    ineligible_member = get_success_data(api.get_member(roster["members"][1]["id"], enrollment_ops_headers))
    assert eligible_member["member_status"] == "ELIGIBLE"
    assert ineligible_member["member_status"] == "INELIGIBLE"
    assert ineligible_member["eligibility_basis"] == "NO_MSK_FLAG"

    assert file_obj["total_monthly_fee_cents"] == 1350000, (
        "the numerator is 9000 * 100 * 1.0 plus 9000 * 100 * 0.5 = 1350000, "
        "divided by the single eligible member and rounded once"
    )
    assert file_obj["screened_member_count"] == 2


# ══════════════════════════════════════════════════════════════════
# The two roster-fee readings
# ══════════════════════════════════════════════════════════════════

def test_roster_fee_actual_vs_expected_payability_variance(api, clinical_ops_headers,
                                                           enrollment_ops_headers):
    """PRD §3.2: "The forward-looking variant projects the eligible denominator
    from the contract rather than from the members who actually screened in, so
    for any roster whose observed eligible share differs from the contractual
    expectation the two variants return different cents."
    PRD §3.2: "`fee_variance_cents` is the chronological total minus the
    provisional total, and is stored as a signed integer."

    Design: Difficulty/dual_variant_calc/roster_fee_actual_vs_expected_payability_variance
    """
    client = setup_client(expected_monthly_engagement_rate=0.60)
    setup_tracks(acute_fee=9000, chronic_fee=12000)
    roster = setup_roster(client["id"], THREE_MEMBER_ROSTER)
    file_obj = roster["file"]

    assert file_obj["member_row_count"] == 3
    assert file_obj["eligible_member_count"] == 2
    assert file_obj["ineligible_member_count"] == 1
    assert file_obj["screened_member_count"] == 3
    assert file_obj["total_monthly_fee_cents"] == 1125000, (
        "the chronological variant divides the weighted numerator by the two "
        "members who actually screened ELIGIBLE"
    )
    assert file_obj["provisional_total_monthly_fee_cents"] == 1250000, (
        "the forward-looking variant divides the identical numerator by "
        "member_row_count * expected_monthly_engagement_rate = 3 * 0.60"
    )
    assert file_obj["fee_variance_cents"] == -125000


def test_roster_fee_variants_disagree_on_the_identical_roster(api, clinical_ops_headers,
                                                              enrollment_ops_headers):
    """PRD §3.2: "When `eligible_member_count` is zero the chronological fee is
    exactly 0 rather than a division error or a null."
    PRD §3.2: "`fee_variance_cents` is the chronological total minus the
    provisional total, and is stored as a signed integer."

    Design: Difficulty/dual_variant_calc/roster_fee_actual_vs_expected_payability_variance
    """
    client = setup_client(expected_monthly_engagement_rate=0.60)
    setup_tracks(acute_fee=9000, chronic_fee=12000)
    roster = setup_roster(client["id"], THREE_MEMBER_ROSTER)
    file_obj = roster["file"]

    assert file_obj["total_monthly_fee_cents"] != file_obj["provisional_total_monthly_fee_cents"], (
        "the two variants disagree on the identical roster"
    )
    assert file_obj["provisional_total_monthly_fee_cents"] == 1250000
    assert file_obj["total_monthly_fee_cents"] == 1125000
    assert file_obj["fee_variance_cents"] == (
        file_obj["total_monthly_fee_cents"] - file_obj["provisional_total_monthly_fee_cents"]
    ), "fee_variance_cents is the chronological total minus the provisional total"
    assert file_obj["fee_variance_cents"] == -125000


def test_roster_fee_nested_rounding_legacy_roster(api, clinical_ops_headers,
                                                   enrollment_ops_headers):
    """PRD §3.2: "the base is reduced to three-quarters of its value by flooring
    it to a whole number of cents, and that flooring is applied to each member's
    base individually before the weighted sum is taken. Summing the unfloored
    bases first and flooring the sum once afterwards returns different cent totals
    whenever any member's base is not an exact multiple of four".

    Design: Difficulty/combinatorial_formula/roster_fee_nested_rounding_legacy_roster
    """
    client = setup_client(
        legal_name="Ridgeway Foods", client_type="EMPLOYER",
        expected_monthly_engagement_rate=0.50)
    setup_tracks(acute_fee=9002, acute_overrides={
        "expected_sessions_per_week": 2, "function_gain_target_points": 12.0,
        "min_adherence_rate": 0.50,
    })
    roster = setup_roster(client["id"], [
        {"external_member_ref": "RW-0001", "full_name": "Pia Nkemdi",
         "date_of_birth": "1974-08-08T00:00:00Z", "musculo_condition_code": "SHOULDER",
         "baseline_pain_score": 6.5, "baseline_function_score": 50.0,
         "red_flag_multipliers": []},
        {"external_member_ref": "RW-0002", "full_name": "Quinn Adeyemi",
         "date_of_birth": "1988-01-25T00:00:00Z", "musculo_condition_code": "NECK",
         "baseline_pain_score": 5.0, "baseline_function_score": 60.0,
         "red_flag_multipliers": [1.15, 1.15]},
    ], roster_format="LEGACY")

    file_obj = roster["file"]
    assert file_obj["roster_format"] == "LEGACY"
    assert file_obj["eligible_member_count"] == 2
    assert file_obj["total_monthly_fee_cents"] == 675100, (
        "the per-member LEGACY base is floor(9002 * 0.75) == 6751, applied twice "
        "before summing"
    )
    assert file_obj["total_monthly_fee_cents"] != 1012600, (
        "flooring the summed total instead would give 1012600 cents, so the pinned "
        "per-member order is observable"
    )


# ══════════════════════════════════════════════════════════════════
# Roster-intake guards and validation precedence
# ══════════════════════════════════════════════════════════════════

def test_file_period_regression_is_refused(api, clinical_ops_headers, enrollment_ops_headers):
    """PRD §3.1: "a new file's `file_period` is checked against the client's
    greatest existing roster period for recency, and a period that is not strictly
    later than that greatest period is rejected with `ERR_FILE_PERIOD_REGRESSION`."

    Design: Corner/validations/file_period_regression_is_refused
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False)
    client_id = scenario["client_id"]

    validate_success(api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-09"),
        enrollment_ops_headers), expected_status=201)

    # The regression is raised when the file is challenged for recency.
    regressed = api.create_eligibility_file(
        create_eligibility_file_payload(
            client_id, file_period="2026-08"),
        enrollment_ops_headers)
    validate_error(regressed, ApiErrorId.ERR_FILE_PERIOD_REGRESSION, expected_status=409)

    files = get_success_data(api.list_eligibility_files(
        enrollment_ops_headers, {"client_account_id": client_id}))
    assert len(files) == 1
    assert files[0]["file_period"] == "2026-09"

    later = api.create_eligibility_file(
        create_eligibility_file_payload(
            client_id, file_period="2026-10"),
        enrollment_ops_headers)
    assert later.status_code == 201, "a strictly later period is accepted"


def test_file_period_regression_outranks_client_not_active(api, clinical_ops_headers,
                                                            billing_ops_headers,
                                                            enrollment_ops_headers):
    """PRD §3.1: "a period that is not strictly later than that greatest period is
    rejected with `ERR_FILE_PERIOD_REGRESSION`."
    PRD §2.11: "Within the business rules the sequence is clinical-safety and
    segregation-of-duties checks first, then state checks, then scheduling and
    capacity checks, then uniqueness and temporal-window checks, and finally
    fiscal checks."

    Design: Corner/validations/file_period_regression_outranks_client_not_active
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False)
    client_id = scenario["client_id"]

    validate_success(api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-09"),
        enrollment_ops_headers), expected_status=201)

    validate_success(api.suspend_client(
        client_id, {"reason": "Contract review"}, billing_ops_headers))

    refused = api.create_eligibility_file(
        create_eligibility_file_payload(
            client_id, file_period="2026-08"),
        enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_FILE_PERIOD_REGRESSION, expected_status=409)

    validate_success(api.reinstate_client(client_id, billing_ops_headers))
    refused_again = api.create_eligibility_file(
        create_eligibility_file_payload(
            client_id, file_period="2026-08"),
        enrollment_ops_headers)
    validate_error(refused_again, ApiErrorId.ERR_FILE_PERIOD_REGRESSION, expected_status=409)


def test_missing_context_header_outranks_business_fiscal_refusal(api, clinical_ops_headers):
    """PRD §2.11: "a request with missing or unrecognised context headers fails
    with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` before anything else is examined".
    PRD §2.1: "If either header is absent, or if `X-User-Role` names a role that
    this API does not declare, the request is rejected with
    `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_context_header_outranks_business_fiscal_refusal
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False)
    client_id = scenario["client_id"]

    bad_headers = build_user_headers("", "NoSuchRole")
    refused = api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-09"), bad_headers)

    validate_error(refused, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
                   expected_status=400)

    accepted = api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-09"),
        ENROLLMENT_OPS)
    assert accepted.status_code == 201, "the failure was purely the context header"


def test_unknown_file_segment_is_not_masked_by_the_screen_body(api, clinical_ops_headers,
                                                                enrollment_ops_headers):
    """PRD §2.9: "A request that names an unknown inner resource under a known
    outer resource resolves the outer resource first and then reports the inner
    failure, still as `ERR_RESOURCE_NOT_FOUND`."
    PRD §2.11: "existence of every path-addressed resource, resolved
    leftmost-first, failing with `ERR_RESOURCE_NOT_FOUND`".

    Design: Corner/validations/unknown_second_segment_does_not_mask_the_first
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False)
    client_id = scenario["client_id"]

    real_file = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client_id), enrollment_ops_headers))

    refused = api.screen_eligibility_file(
        "00000000-0000-4000-8000-000000000000", enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)

    untouched = get_success_data(api.get_eligibility_file(real_file["id"], enrollment_ops_headers))
    assert untouched["file_status"] == "INGESTED", "the real file was not touched"

def test_the_legacy_floor_is_applied_per_member_not_to_the_sum(api, clinical_ops_headers,
                                                               enrollment_ops_headers):
    """PRD §3.2: "that flooring is applied to each member's base individually
    before the weighted sum is taken. Summing the unfloored bases first and
    flooring the sum once afterwards returns different cent totals whenever any
    member's base is not an exact multiple of four, so the per-member order is
    pinned rather than left to choice."
    PRD §3.2: "The weight is 1.00 for a member whose `member_status` is `ELIGIBLE`
    and 0.50 for a member whose `member_status` is `INELIGIBLE`."

    Design: Difficulty/combinatorial_formula/roster_fee_nested_rounding_legacy_roster
    """
    client = setup_client(
        legal_name="Ridgeway Foods", client_type="EMPLOYER",
        expected_monthly_engagement_rate=0.50)
    setup_tracks(acute_fee=9002, acute_overrides={
        "expected_sessions_per_week": 2, "function_gain_target_points": 12.0,
        "min_adherence_rate": 0.50,
    })
    roster = setup_roster(client["id"], [
        {"external_member_ref": "RW-0001", "full_name": "Pia Nkemdi",
         "date_of_birth": "1974-08-08T00:00:00Z", "musculo_condition_code": "SHOULDER",
         "baseline_pain_score": 6.5, "baseline_function_score": 50.0},
        {"external_member_ref": "RW-0002", "full_name": "Quinn Adeyemi",
         "date_of_birth": "1988-01-25T00:00:00Z", "musculo_condition_code": "NECK",
         "baseline_pain_score": 5.0, "baseline_function_score": 60.0},
    ], roster_format="LEGACY")

    file_obj = roster["file"]
    per_member_base = (9002 * 3) // 4
    assert per_member_base == 6751
    assert file_obj["total_monthly_fee_cents"] == (
        file_obj["eligible_member_count"] * per_member_base * 100
    ) // file_obj["eligible_member_count"], (
        "the chronological total is the per-member floored base, weighted and "
        "divided by the eligible count"
    )
    assert file_obj["total_monthly_fee_cents"] == 675100
