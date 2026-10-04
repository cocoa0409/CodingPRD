"""Enrollment, rate filings, premium aging, and claim-intake computed fields."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_hospital_staff_headers,
    set_clock,
    create_and_file_filing,
    create_active_hospital,
    create_policy,
    create_policy_past_waiting,
    create_policy_payload,
    create_hospital_payload,
    setup_active_environment,
    submit_claim,
    assert_claim_totals_consistent,
    assert_instant_equals,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RATE_ADMIN = TEST_USERS["rate_filing_admin_headers"]


# ---------------------------------------------------------------------------
# Queue A: Difficulty / dual_variant_calc
# ---------------------------------------------------------------------------

def test_recalc_reselects_newest_effective_filing_but_filed_base_frozen(api):
    """PRD 3.3: "The applied filing is re-selected as the newest EFFECTIVE
    filing for the policy's territory and species whose filing_effective_date
    is on or before the current logical date — note the contrast with
    enrollment, which selects relative to coverage_start — with the same
    tie-break (latest effective_at, then latest created_at)."
    PRD 3.3: "The filed_base_cents captured at enrollment is never rewritten —
    it remains the historical record — while current_monthly_premium_cents,
    applied_filing_id, and next_birthday (advanced by one year) all update,
    and the policy's version increments."

    Design: Difficulty/dual_variant_calc/premium_enrollment_base_vs_age_band_recalc
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_and_file_filing(
        base_monthly_premium_cents=100000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2026-09-01",
        regulator_reference="CA-2026-001",
    )
    policy = create_policy(pet_date_of_birth="2025-09-01", coverage_start="2026-09-01")
    assert policy["filed_base_cents"] == 100000
    # Pet turns 1 exactly at coverage_start -> band 1 multiplier 1.0025 applies.
    assert policy["current_monthly_premium_cents"] == 100250
    assert policy["applied_filing_id"] == f1["id"]

    f2 = create_and_file_filing(
        base_monthly_premium_cents=110000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2027-08-01",
        regulator_reference="CA-2027-002",
    )
    set_clock("2027-09-01T00:00:00Z")

    resp = api.recalculate_premium(policy["id"], ADMIN)
    updated = validate_success(resp)
    assert updated["filed_base_cents"] == 100000
    # Band 2 -> greatest declared band at or below it is "1" -> 1.0025:
    # 110000 * 1.0025 = 110275 half-up.
    assert updated["current_monthly_premium_cents"] == 110275
    assert updated["applied_filing_id"] == f2["id"]
    assert updated["next_birthday"] == "2028-09-01"
    assert updated["enrollment_status"] == "FULLY_ACTIVE"


def test_recalc_uses_current_date_filing_not_coverage_start_filing(api):
    """PRD 3.3: "The chosen filing becomes the policy's applied_filing_id; its
    base_monthly_premium_cents is locked into the policy's filed_base_cents as
    a historical record, and the initial current_monthly_premium_cents is
    computed from it."
    PRD 3.3: "Recalculation requires the policy's lifecycle_status to be
    ACTIVE and the current logical date to be at or past next_birthday."

    Design: Difficulty/dual_variant_calc/premium_enrollment_base_vs_age_band_recalc
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_and_file_filing(
        base_monthly_premium_cents=100000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2026-09-01",
        regulator_reference="CA-2026-001",
    )
    policy = create_policy(pet_date_of_birth="2025-09-01", coverage_start="2026-09-01")
    f2 = create_and_file_filing(
        base_monthly_premium_cents=110000,
        age_band_multipliers={"0": 1.0, "1": 1.0025},
        filing_effective_date="2027-08-01",
        regulator_reference="CA-2027-002",
    )
    set_clock("2027-09-01T00:00:00Z")
    resp = api.recalculate_premium(policy["id"], ADMIN)
    updated = validate_success(resp)
    # enrollment variant froze filed_base at F1's base; recalc variant priced
    # off F2's base with the band-1 multiplier, half-up: 110000 * 1.0025.
    assert updated["filed_base_cents"] == 100000
    assert updated["current_monthly_premium_cents"] == 110275
    assert updated["applied_filing_id"] == f2["id"]


# ---------------------------------------------------------------------------
# Queue A: Difficulty / combinatorial_formula (age-band fallback)
# ---------------------------------------------------------------------------

def test_age_band_falls_back_to_greatest_declared_band(api):
    """PRD 3.3: "The multiplier is the filing's age_band_multipliers entry for
    the computed band if present; otherwise the multiplier of the greatest
    declared band at or below the computed band; otherwise 1.0 if no declared
    band is at or below it."

    Design: Difficulty/combinatorial_formula/age_band_fallback_and_premium_rounding
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_and_file_filing(
        base_monthly_premium_cents=100000,
        age_band_multipliers={"0": 1.0, "1": 1.05},
        filing_effective_date="2026-09-01",
        regulator_reference="CA-2026-009",
    )
    resp = api.create_policy(
        create_policy_payload(
            owner_name="Cy Okafor", pet_name="Rex", breed="Lab",
            pet_date_of_birth="2020-06-15", coverage_start="2026-09-01",
        ),
        TEST_USERS["pet_owner_headers"],
    )
    policy = validate_success(resp, expected_status=201)
    # Pet age band at coverage_start is 6; no "6" key, so the greatest
    # declared band at or below 6 is band "1" -> multiplier 1.05.
    assert policy["current_monthly_premium_cents"] == 105000
    assert policy["filed_base_cents"] == 100000
    assert policy["next_birthday"] == "2027-06-15"
    assert policy["applied_filing_id"] == f1["id"]


def test_age_band_fallback_premium_rounds_half_up(api):
    """PRD 3.3: "The new current_monthly_premium_cents is the filing's
    base_monthly_premium_cents times that multiplier, rounded half-up to
    whole cents."
    PRD 3.1: "an age_band_multipliers map from integer age band — the floor
    of the pet's age in whole years — to a decimal multiplier"

    Design: Difficulty/combinatorial_formula/age_band_fallback_and_premium_rounding
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing(
        base_monthly_premium_cents=100000,
        age_band_multipliers={"0": 1.0, "1": 1.05},
        filing_effective_date="2026-09-01",
        regulator_reference="CA-2026-009",
    )
    resp = api.create_policy(
        create_policy_payload(pet_date_of_birth="2020-06-15", coverage_start="2026-09-01"),
        TEST_USERS["pet_owner_headers"],
    )
    policy = validate_success(resp, expected_status=201)
    # 100000 * 1.05 = 105000 exactly; half-up rounding keeps integer cents.
    assert policy["current_monthly_premium_cents"] == 105000
    assert policy["filed_base_cents"] == 100000
    assert policy["next_birthday"] == "2027-06-15"


# ---------------------------------------------------------------------------
# Queue B: Corner / entities
# ---------------------------------------------------------------------------

def test_hospital_create_returns_applied_state_and_zero_ledger(api):
    """PRD 3.2: "The hospital begins in APPLIED status with a
    running_ledger_balance_cents of zero."
    PRD 2.2: "The api_request_id is a server-generated unique identifier for
    the request that starts with req_."

    Design: Corner/entities/hospital_create_returns_declared_fields_and_applied_state
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_hospital(create_hospital_payload(), ADMIN)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    hospital = validate_success(resp, expected_status=201)
    assert hospital["status"] == "APPLIED"
    assert hospital["version"] == 1
    assert hospital["running_ledger_balance_cents"] == 0
    assert hospital["training_completed_at"] is None


def test_filing_create_defaults_to_draft_with_null_stamps(api):
    """PRD 3.1: "Creation is a 201 and the filing begins life in DRAFT status."
    PRD 3.1: "Filing with the regulator transitions a filing from DRAFT to
    FILED, stamps filed_at with the current logical clock, and increments the
    filing's version."

    Design: Corner/entities/filing_create_defaults_to_draft
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_rate_filing(
        {
            "territory_code": "941",
            "state_code": "CA",
            "species": "DOG",
            "base_monthly_premium_cents": 100000,
            "age_band_multipliers": {"0": 1.0, "1": 1.0025},
            "filing_effective_date": "2026-09-01",
            "regulator_reference": "CA-2026-001",
        },
        RATE_ADMIN,
    )
    filing = validate_success(resp, expected_status=201)
    assert filing["status"] == "DRAFT"
    assert filing["filed_at"] is None
    assert filing["effective_at"] is None
    assert filing["version"] == 1


def test_claim_create_zeroes_computed_totals_until_adjudication(api):
    """PRD 3.5: "Submission creates the claim in SUBMITTED status with all
    totals zeroed until adjudication, mints the lines as ClaimLine resources
    numbered by seq from 1 upward in submission order, and returns 201."

    Design: Corner/entities/claim_create_zeroes_computed_totals_until_adjudication
    """
    hospital, policy = setup_active_environment()
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-02",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 50000,
                 "category": "TREATMENT", "condition_code": "DXA"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    claim = validate_success(resp, expected_status=201)
    assert claim["status"] == "SUBMITTED"
    assert claim["version"] == 1
    assert claim["total_invoice_cents"] == 0
    assert claim["eligible_cents"] == 0
    assert claim["reimbursement_cents"] == 0
    assert claim["deductible_applied_cents"] == 0
    assert claim["member_responsibility_cents"] == 0
    assert claim["payment_id"] is None
    assert claim["adjudicated_at"] is None
    assert claim["denial_reason"] is None
    assert_claim_totals_consistent(claim)


def test_policy_create_computes_waiting_windows_and_next_birthday(api):
    """PRD 3.3: "At creation the policy is INJURY_WAITING and ACTIVE, its
    waiting windows are computed — injury_waiting_end at coverage_start
    00:00:00Z plus the injury waiting day count INJURY_WAITING_DAYS, which is
    5 days, and illness_waiting_end at coverage_start 00:00:00Z plus the
    illness waiting day count ILLNESS_WAITING_DAYS, which is 14 days — and
    its next_birthday is computed for the premium sweep."

    Design: Corner/entities/policy_create_computes_waiting_windows_and_next_birthday
    """
    set_clock("2026-09-01T00:00:00Z")
    filing = create_and_file_filing()
    # pet_date_of_birth is chosen off the coverage_start boundary so the
    # next_birthday anniversary is unambiguous (2026-10-15 > 2026-09-01).
    resp = api.create_policy(
        create_policy_payload(pet_date_of_birth="2025-10-15"),
        TEST_USERS["pet_owner_headers"],
    )
    policy = validate_success(resp, expected_status=201)
    assert_instant_equals(policy["injury_waiting_end"], "2026-09-06T00:00:00Z")
    assert_instant_equals(policy["illness_waiting_end"], "2026-09-15T00:00:00Z")
    assert policy["next_birthday"] == "2026-10-15"
    assert policy["enrollment_status"] == "INJURY_WAITING"
    assert policy["lifecycle_status"] == "ACTIVE"
    assert policy["filed_base_cents"] == 100000
    assert policy["current_monthly_premium_cents"] == 100000
    assert policy["applied_filing_id"] == filing["id"]


def test_hospitals_list_paginates_and_filters(api):
    """PRD 2.3: "limit defaults to 10, must be at least 1, and must not exceed
    100. offset defaults to 0. List results are always sorted by created_at
    ascending. The meta block of a list response carries limit, offset,
    total_count, and has_more, where total_count is the number of records
    matching the filter (not just the returned page) and has_more indicates
    whether further records exist beyond the returned window."

    Design: Corner/entities/hospitals_list_paginates_and_filters
    """
    set_clock("2026-09-01T00:00:00Z")
    h1 = get_success_data(api.create_hospital(create_hospital_payload(), ADMIN))
    h2 = get_success_data(api.create_hospital(
        create_hospital_payload(legal_name="North Beach Vet", bank_account_ref="BA-002"),
        ADMIN,
    ))
    get_success_data(api.approve_hospital(
        h2["id"], {"expected_hospital_version": h2["version"]}, ADMIN
    ))

    resp = api.list_hospitals(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert data[0]["id"] == h1["id"], "sorted by created_at ascending"

    resp = api.list_hospitals(ADMIN, params={"limit": 1, "offset": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == h2["id"]

    resp = api.list_hospitals(ADMIN, params={"status": "APPLIED"})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == h1["id"]

    resp = api.list_hospitals(ADMIN)
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["limit"] == 10


def test_policy_get_not_found(api):
    """PRD 2.7: "Existence of path identifiers, validated left to right as
    they appear in the URL — hospitalId before policyId before claimId before
    appealId before filingId before reportId — each missing identifier
    yielding its specific not-found error (ERR_HOSPITAL_NOT_FOUND,
    ERR_POLICY_NOT_FOUND, ERR_CLAIM_NOT_FOUND, ERR_APPEAL_NOT_FOUND,
    ERR_FILING_NOT_FOUND, ERR_REPORT_NOT_FOUND)."

    Design: Corner/entities/policy_get_not_found
    """
    resp = api.get_policy(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND)


def test_claim_create_missing_policy_id_rejected(api):
    """PRD 2.7: "Malformed payloads — a missing required field, a wrong type,
    a non-positive invoice line amount, an enum violation, or a treatment
    line missing its condition code at intake — are rejected with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/claim_create_missing_policy_id_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    resp = api.create_claim(
        {
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-02",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 50000,
                 "category": "TREATMENT", "condition_code": "DXA"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_claim_line_invalid_enum_category_rejected(api):
    """PRD 3.5: "Each line carries a description, a positive integer
    amount_cents (a non-positive amount is ERR_INVALID_REQUEST), a category
    of TREATMENT, EXAM_FEE, TAX, or OTHER_EXCLUDED, and — mandatory exactly
    when the category is TREATMENT — a condition_code naming the condition
    the line treats."
    PRD 2.7: "Malformed payloads — a missing required field, a wrong type, a
    non-positive invoice line amount, an enum violation, or a treatment line
    missing its condition code at intake — are rejected with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/claim_line_invalid_enum_category_rejected
    """
    hospital, policy = setup_active_environment()
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "hospital_id": hospital["id"],
            "visit_date": "2026-10-02",
            "claim_type": "INJURY",
            "lines": [
                {"description": "er", "amount_cents": 50000,
                 "category": "SURGERY", "condition_code": "DXA"}
            ],
        },
        make_hospital_staff_headers(hospital["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"policy_id": policy["id"]})
    )
    assert len(data) == 0


def test_medical_record_has_no_update_surface(api):
    """PRD 2.4: "Two resources deliberately carry only id and created_at:
    MedicalRecord and ReconciliationReport have no updated_at and no version
    field, because a medical record is an immutable clinical artifact and a
    reconciliation report transitions only its status without versioned
    mutation."
    PRD 3.4: "A record's appeal_id is null at upload; it is set only when the
    record is later attached to an appeal."

    Design: Corner/entities/medical_record_has_no_update_endpoint
    """
    from test_helpers import upload_medical_record, assert_medical_record
    set_clock("2026-09-01T00:00:00Z")
    create_and_file_filing()
    hospital = create_active_hospital()
    policy = create_policy()
    record = upload_medical_record(policy, hospital)
    assert_medical_record(record)
    assert record["appeal_id"] is None
    data, meta = validate_paginated(
        api.list_policy_medical_records(policy["id"], TEST_USERS["adjuster_1_headers"])
    )
    assert len(data) == 1
    assert data[0]["id"] == record["id"]
    assert "updated_at" not in data[0]
    assert "version" not in data[0]


def test_claim_lines_require_existing_claim_parent(api):
    """PRD 2.7: "Existence of path identifiers, validated left to right as
    they appear in the URL — hospitalId before policyId before claimId before
    appealId before filingId before reportId — each missing identifier
    yielding its specific not-found error (ERR_HOSPITAL_NOT_FOUND,
    ERR_POLICY_NOT_FOUND, ERR_CLAIM_NOT_FOUND, ERR_APPEAL_NOT_FOUND,
    ERR_FILING_NOT_FOUND, ERR_REPORT_NOT_FOUND)."

    Design: Corner/entities/claim_lines_require_existing_claim_parent
    """
    resp = api.list_claim_lines_of_claim(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)
