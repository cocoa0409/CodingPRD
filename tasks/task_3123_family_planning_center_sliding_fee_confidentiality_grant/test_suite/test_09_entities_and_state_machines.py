"""Breadth tests: entity creation defaults, computed fields, and pagination."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    set_clock, create_affiliate, create_affiliate_payload,
    create_catalog_entry, create_fee_tier, create_patient,
    create_patient_payload, create_assessment, create_assessment_payload,
    get_patient,
    is_valid_uuid, assert_affiliate, assert_encounter,
    setup_tx_clinic, setup_patient_with_assessment, setup_assessed_encounter,
    NON_EXISTENT_UUID,
    TEST_USERS, FPL_INCOME_H1_PCT_265, ENC_START, ENC_END,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_affiliate_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "A newly registered affiliate enters `ACTIVE` status with
    `grant_cycle_open` set to `true` and `version` initialized to 1."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix. `created_at`
    and `updated_at` are ISO 8601 UTC timestamps with three fractional
    digits."

    Design: Corner/entities/affiliate_create_returns_defaults_and_system_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    affiliate = validate_success(
        api_client.create_affiliate(
            create_affiliate_payload(affiliate_code="PP-NM-02",
                                     state_code="NM",
                                     low_income_priority_quota=40),
            ADMIN,
        ),
        201,
    )
    assert_affiliate(affiliate)
    assert is_valid_uuid(affiliate["id"])
    assert affiliate["status"] == "ACTIVE"
    assert affiliate["grant_cycle_open"] is True
    assert affiliate["version"] == 1
    assert affiliate["affiliate_code"] == "PP-NM-02"
    assert affiliate["state_code"] == "NM"
    assert affiliate["low_income_priority_quota"] == 40


def test_patient_get_round_trips_computed_is_minor(api):
    """PRD §3.3: "The patient's `is_minor` flag is computed by the server: it
    is `true` exactly when the logical-clock current date minus
    `date_of_birth` is less than 18 years."
    PRD §2.5: "every `Patient`'s `is_minor` flag is recomputed against the
    new current date."

    A patient born 2012-01-01 reads is_minor true at clock 2026-09-01 and
    false once the clock passes their 18th birthday.

    Design: Corner/entities/patient_get_round_trips_computed_is_minor
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    patient = create_patient(aff["id"], external_ref="MIN-1",
                             date_of_birth="2012-01-01")
    now = validate_success(api_client.get_patient(patient["id"], PRIVACY))
    assert now["is_minor"] is True, (
        f"born 2012-01-01 at clock 2026-09-01 must be a minor, got "
        f"{now['is_minor']}"
    )
    set_clock("2030-01-02T00:00:00Z")
    later = validate_success(api_client.get_patient(patient["id"], PRIVACY))
    assert later["is_minor"] is False


def test_household_assessment_household_size_zero_rejected(api):
    """PRD §3.3: "a `FrontDeskStaff` operator creates one by submitting
    `household_size` (an integer count of household members, at least 1)".
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

    household_size 0 is a 400 ERR_INVALID_REQUEST and persists no assessment.

    Design: Corner/entities/household_assessment_household_size_zero_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    patient = create_patient(aff["id"], external_ref="HS-1",
                             date_of_birth="1990-01-01")
    payload = create_assessment_payload(household_size=0,
                                        annual_income_cents=1000000,
                                        income_basis="DOCUMENTED")
    payload["expected_patient_version"] = patient["version"]
    res = api_client.create_assessment(patient["id"], payload, FRONT_DESK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    rows, meta = validate_paginated(
        api_client.list_assessments(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 0
    assert meta["total_count"] == 0


def test_fee_tier_defaults_nominal_copay_to_zero(api):
    """PRD §3.2: "an optional `nominal_copay_cents` floor defaulting to 0
    that the patient owes even at full discount".

    Omitting nominal_copay_cents stores integer 0, not null.

    Design: Corner/entities/fee_tier_defaults_nominal_copay_to_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    payload = {
        "tier_code": "Z",
        "fpl_pct_min_inclusive": 0,
        "fpl_pct_max_exclusive": 50,
        "discount_pct": 100,
        "requires_documentation": False,
    }
    tier = validate_success(
        api_client.create_fee_tier(aff["id"], payload, ADMIN), 201
    )
    assert tier["nominal_copay_cents"] == 0
    assert isinstance(tier["nominal_copay_cents"], int)


def test_patient_list_paginates_with_envelope_fields(api):
    """PRD §2.3: "All list endpoints accept the optional query parameters
    `limit` and `offset`. `limit` defaults to 10, accepts a minimum of 1 and
    a maximum of 100; `offset` defaults to 0 and accepts any non-negative
    integer. ... The `meta` block of any paginated response contains `limit`,
    `offset`, `total_count`, and `has_more`."

    Three patients: limit=2&offset=0 returns 2 rows with total_count 3 and
    has_more true; offset=2 returns 1 row with has_more false; no params
    returns all 3.

    Design: Corner/entities/patient_list_paginates_with_envelope_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    for i, year in enumerate((1990, 1991, 1992), start=1):
        create_patient(aff["id"], external_ref=f"LP-{i}",
                       date_of_birth=f"{year}-01-01")

    page1, meta1 = validate_paginated(
        api_client.list_patients(aff["id"], FRONT_DESK,
                                 params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_patients(aff["id"], FRONT_DESK,
                                 params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta3 = validate_paginated(
        api_client.list_patients(aff["id"], FRONT_DESK)
    )
    assert len(all_rows) == 3
    assert meta3["limit"] == 10
    assert meta3["offset"] == 0


def test_claim_get_unknown_id_returns_claim_not_found(api):
    """PRD §2.8: "The not-found error identifiers follow the per-entity
    pattern: `ERR_AFFILIATE_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, ...
    `ERR_CLAIM_NOT_FOUND` ... Each carries HTTP 404."

    A syntactically valid but unallocated claim id yields 404
    ERR_CLAIM_NOT_FOUND with the error envelope's error_id and message.

    Design: Corner/entities/claim_get_unknown_id_returns_claim_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.get_claim(NON_EXISTENT_UUID, BILLING)
    error_data = validate_error(res, "ERR_CLAIM_NOT_FOUND",
                                expected_status=404)
    assert "message" in error_data
    assert res.json()["response_type"] == "error"


def test_encounter_initial_state_is_scheduled_unbilled(api):
    """PRD §3.4: "New encounters enter clinical status `SCHEDULED` and
    billing status `UNBILLED`."
    PRD §2.4: "`version` is an integer that increments on every mutation of
    the resource".

    A fresh encounter starts SCHEDULED / UNBILLED at version 1, and with a
    0%-discount tier its charge equals the full fee.

    Design: Corner/state_machines/encounter_initial_state_is_scheduled_unbilled
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    enc = ctx["encounter"]
    assert_encounter(enc)
    assert enc["clinical_status"] == "SCHEDULED"
    assert enc["billing_status"] == "UNBILLED"
    assert enc["version"] == 1
    assert enc["patient_charge_cents"] == 20000, (
        "tier D applies no discount — charge equals full_fee_cents"
    )


def test_encounter_start_before_scheduled_start_rejected(api):
    """PRD §3.5: "The start is permitted only when the logical clock has
    reached `scheduled_start`; attempting to start early is rejected with
    `ERR_INVALID_STATE`."

    With the clock still at 2026-09-01 and the encounter slotted 2026-09-10,
    start is a 409 ERR_INVALID_STATE and the encounter stays SCHEDULED.

    Design: Corner/state_machines/encounter_start_before_scheduled_start_rejected
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    enc_id = ctx["encounter"]["id"]
    res = api_client.start_encounter(enc_id, TEST_USERS["clinician_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    enc_after = validate_success(api_client.get_encounter(enc_id, FRONT_DESK))
    assert enc_after["clinical_status"] == "SCHEDULED"


def test_encounter_complete_from_scheduled_is_invalid_transition(api):
    """PRD §3.5: "A `Clinician` completes an `IN_PROGRESS` encounter,
    transitioning clinical status to `COMPLETED`."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict".

    Complete is only legal from IN_PROGRESS; from SCHEDULED it is 409 and
    neither axis moves.

    Design: Corner/state_machines/encounter_complete_from_scheduled_is_invalid_transition
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    enc_id = ctx["encounter"]["id"]
    set_clock("2026-09-10T10:00:00Z")
    res = api_client.complete_encounter(enc_id, TEST_USERS["clinician_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    enc_after = validate_success(api_client.get_encounter(enc_id, FRONT_DESK))
    assert enc_after["clinical_status"] == "SCHEDULED"
    assert enc_after["billing_status"] == "UNBILLED"


def test_affiliate_terminal_close_locks_all_further_transitions(api):
    """PRD §3.1: "Closure is terminal."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict".

    From CLOSED, suspend is a 409 ERR_INVALID_STATE and the affiliate remains
    CLOSED.

    Design: Corner/state_machines/affiliate_terminal_close_locks_all_further_transitions
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    closed = validate_success(api_client.close_affiliate(aff["id"], ADMIN))
    assert closed["status"] == "CLOSED"

    res = api_client.suspend_affiliate(aff["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api_client.get_affiliate(aff["id"], ADMIN))
    assert after["status"] == "CLOSED"


def test_referral_order_full_path_open_acknowledged_completed(api):
    """PRD §3.9: "New referrals enter `OPEN`. ... An `OPEN` referral may be
    acknowledged (`OPEN` → `ACKNOWLEDGED`) or withdrawn (`OPEN` →
    `WITHDRAWN`). An `ACKNOWLEDGED` referral may be completed (`ACKNOWLEDGED`
    → `COMPLETED`) or withdrawn (`ACKNOWLEDGED` → `WITHDRAWN`). `COMPLETED`
    and `WITHDRAWN` are terminal."

    The pipeline runs OPEN -> ACKNOWLEDGED -> COMPLETED, and withdraw from
    the terminal COMPLETED state is rejected.

    Design: Corner/state_machines/referral_order_full_path_open_acknowledged_completed
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    enc_id = ctx["encounter"]["id"]
    referral = validate_success(
        api_client.create_referral(
            enc_id,
            {"requested_service_code": "PRENATAL_CARE",
             "receiving_org": "County Health",
             "reason_code": "OUT_OF_SCOPE_AFFILIATE"},
            TEST_USERS["clinician_headers"],
        ),
        201,
    )
    assert referral["status"] == "OPEN"

    acked = validate_success(
        api_client.acknowledge_referral(referral["id"],
                                        TEST_USERS["care_coordinator_headers"])
    )
    assert acked["status"] == "ACKNOWLEDGED"

    completed = validate_success(
        api_client.complete_referral(referral["id"],
                                     TEST_USERS["care_coordinator_headers"])
    )
    assert completed["status"] == "COMPLETED"

    res = api_client.withdraw_referral(referral["id"],
                                       TEST_USERS["care_coordinator_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(
        api_client.get_referral(referral["id"],
                                TEST_USERS["care_coordinator_headers"])
    )
    assert after["status"] == "COMPLETED"


def test_grant_report_finalize_then_amendment_supersedes(api):
    """PRD §3.10: "Amendment is the only path past `FINALIZED`: when a new
    report is created with `amendment_of` pointing at a `FINALIZED` report,
    the amended report transitions to `SUPERSEDED`, and the amending report
    captures the amended report's aggregates as its baseline."

    The amendment lands as DRAFT pointing at the original, the original flips
    to SUPERSEDED, and the reverse-reachability list shows exactly one
    amendment.

    Design: Corner/state_machines/grant_report_finalize_then_amendment_supersedes
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    set_clock("2026-10-02T00:00:00Z")
    report1 = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff["version"]},
            ADMIN,
        ),
        201,
    )
    validate_success(api_client.finalize_grant_report(report1["id"], ADMIN))
    aff_after = validate_success(api_client.get_affiliate(aff["id"], ADMIN))

    report2 = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "WEIGHTED_AVERAGE",
             "amendment_of": report1["id"],
             "expected_affiliate_version": aff_after["version"]},
            ADMIN,
        ),
        201,
    )
    assert report2["status"] == "DRAFT"
    assert report2["amendment_of"] == report1["id"]

    original = validate_success(
        api_client.get_grant_report(report1["id"], ADMIN)
    )
    assert original["status"] == "SUPERSEDED", (
        "the amended report transitions to SUPERSEDED as a system side effect"
    )
    amendments, meta = validate_paginated(
        api_client.list_report_amendments(report1["id"], ADMIN)
    )
    assert len(amendments) == 1
    assert amendments[0]["id"] == report2["id"]
