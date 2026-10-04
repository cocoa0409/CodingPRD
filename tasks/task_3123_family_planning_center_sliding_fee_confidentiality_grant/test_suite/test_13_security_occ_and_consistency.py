"""Breadth tests: auth, RBAC, optimistic concurrency, versioning, consistency."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    set_clock, create_affiliate, create_fee_tier, create_patient,
    create_assessment, create_assessment_payload,
    create_privacy_hold_payload,
    setup_tx_clinic, setup_assessed_encounter, setup_submitted_claim,
    get_claim,
    NON_EXISTENT_UUID,
    TEST_USERS, FPL_INCOME_H1_PCT_174, FPL_INCOME_H1_PCT_265,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]
SUPPLY = TEST_USERS["supply_coordinator_headers"]
CARE = TEST_USERS["care_coordinator_headers"]


def test_error_missing_auth_headers(api):
    """PRD §2.1: "A request missing either header, or carrying a role string
    the server does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.10: "The order is: (1) header presence and shape, surfaced as
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; ... (3) path-parameter
    existence, surfaced as the appropriate `ERR_*_NOT_FOUND`".

    A request with neither header on a non-existent affiliate is 400, not
    404 — priority 1 beats priority 3.

    Design: Corner/errors/error_missing_auth_headers
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.get_affiliate(NON_EXISTENT_UUID, headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)


def test_error_insufficient_permissions_for_role(api):
    """PRD §2.1: "the server verifies that the named role is permitted to
    invoke the operation; a violation is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "POST | `/family-planning/affiliates/{id}/fee-tiers` | Add a
    sliding-fee tier band | GrantAdministrator".

    A Clinician attempting to create a fee tier is 403 and nothing persists.

    Design: Corner/errors/error_insufficient_permissions_for_role
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    res = api_client.create_fee_tier(
        aff["id"],
        {"tier_code": "X", "fpl_pct_min_inclusive": 0,
         "fpl_pct_max_exclusive": 100, "discount_pct": 50,
         "requires_documentation": False},
        CLINICIAN,
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    rows, meta = validate_paginated(
        api_client.list_fee_tiers(aff["id"], ADMIN)
    )
    assert len(rows) == 0


def test_error_stale_version_on_assessment_create(api):
    """PRD §2.9: "When a client creates a `HouseholdAssessment` for a
    patient, the request must carry `expected_patient_version` matching the
    patient's current `version`. If another writer has advanced the patient's
    `version` since the client last read it ... the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412), forcing the writer to re-read the patient
    before superseding someone else's assessment."

    The second create carrying the pre-first-assessment version is 412; a
    retry with the re-read version succeeds and supersedes.

    Design: Corner/errors/error_stale_version_on_assessment_create
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    patient = create_patient(clinic["affiliate"]["id"], external_ref="OCC-1",
                             date_of_birth="1990-01-01")
    stale_version = patient["version"]
    create_assessment(patient, household_size=1,
                      annual_income_cents=FPL_INCOME_H1_PCT_265,
                      income_basis="DOCUMENTED")

    payload = create_assessment_payload(
        household_size=2, annual_income_cents=FPL_INCOME_H1_PCT_265,
        income_basis="DOCUMENTED",
    )
    payload["expected_patient_version"] = stale_version
    res = api_client.create_assessment(patient["id"], payload, FRONT_DESK)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    patient_now = validate_success(
        api_client.get_patient(patient["id"], FRONT_DESK)
    )
    payload["expected_patient_version"] = patient_now["version"]
    retry = validate_success(
        api_client.create_assessment(patient["id"], payload, FRONT_DESK), 201
    )
    assert retry["status"] == "CURRENT"

    rows, meta = validate_paginated(
        api_client.list_assessments(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 2, "one SUPERSEDED and one CURRENT"


def test_front_desk_cannot_adjudicate_claims(api):
    """PRD §2.1: "the server verifies that the named role is permitted to
    invoke the operation; a violation is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "POST | `/family-planning/claims/{claimId}/adjudicate` | Apply a
    payer payment | BillingSpecialist".

    FrontDeskStaff attempting adjudication is 403; paid_cents does not move.

    Design: Corner/rbac/front_desk_cannot_adjudicate_claims
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-R1",
    )
    claim_id = ctx["claim"]["id"]
    res = api_client.adjudicate_claim(claim_id, {"amount_cents": 10000},
                                      FRONT_DESK)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    claim_after = get_claim(claim_id)
    assert claim_after["paid_cents"] == 0
    assert claim_after["status"] == "SUBMITTED"


def test_billing_specialist_cannot_manage_privacy_holds(api):
    """PRD §2.1: "a violation is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §3.11: "A `PrivacyOfficer` may place a privacy hold on a patient".

    BillingSpecialist attempting to place a hold is 403 and no hold persists.

    Design: Corner/rbac/billing_specialist_cannot_manage_privacy_holds
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    patient = create_patient(clinic["affiliate"]["id"], external_ref="RB-2",
                             date_of_birth="1990-01-01")
    res = api_client.create_privacy_hold(
        patient["id"],
        create_privacy_hold_payload(
            hold_start="2026-09-01T00:00:00Z",
            hold_end="2026-10-01T00:00:00Z", scope="ALL",
            authorized_staff_ids=[],
        ),
        BILLING,
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    rows, meta = validate_paginated(
        api_client.list_privacy_holds(patient["id"], PRIVACY)
    )
    assert len(rows) == 0


def test_supply_coordinator_cannot_create_referrals(api):
    """PRD §2.1: "a violation is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §3.9: "Either a `Clinician` or a `CareCoordinator` may originate a
    referral".

    SupplyCoordinator attempting referral creation on a valid encounter is
    403 and nothing persists.

    Design: Corner/rbac/supply_coordinator_cannot_create_referrals
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    res = api_client.create_referral(
        ctx["encounter"]["id"],
        {"requested_service_code": "PRENATAL_CARE",
         "receiving_org": "County Health",
         "reason_code": "OUT_OF_SCOPE_STATE_LAW"},
        SUPPLY,
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    rows, meta = validate_paginated(
        api_client.list_referrals(ctx["encounter"]["id"], CARE)
    )
    assert len(rows) == 0


def test_occ_stale_version_on_grant_report_create(api):
    """PRD §2.9: "When a client creates a `GrantReport` for an affiliate —
    whether an initial report or an amendment — the request must carry
    `expected_affiliate_version` matching the affiliate's current `version`.
    A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    After one report create bumps the affiliate version, a second create with
    the pre-bump version is 412; the retry with the re-read version succeeds.

    Design: Corner/cross_cutting_layers/occ_stale_version_on_grant_report_create
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
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
    assert report1["status"] == "DRAFT"

    res = api_client.create_grant_report(
        aff["id"],
        {"period_start": "2026-10-01T00:00:00Z",
         "period_end": "2026-11-01T00:00:00Z",
         "valuation_variant": "FIFO",
         "expected_affiliate_version": aff["version"]},
        ADMIN,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    aff_now = validate_success(api_client.get_affiliate(aff["id"], ADMIN))
    report2 = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-10-01T00:00:00Z",
             "period_end": "2026-11-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff_now["version"]},
            ADMIN,
        ),
        201,
    )
    assert report2["status"] == "DRAFT"
    rows, meta = validate_paginated(
        api_client.list_grant_reports(aff["id"], ADMIN)
    )
    assert len(rows) == 2


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "`version` is an integer that increments on every mutation
    of the resource and is the currency of optimistic concurrency."
    PRD §3.1: "Either transition increments the affiliate's `version` by 1
    and refreshes `updated_at`."

    Reads leave version at 1; suspend sets 2, reinstate sets 3, and
    updated_at refreshes while created_at is stable.

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    assert aff["version"] == 1

    read = validate_success(api_client.get_affiliate(aff["id"], ADMIN))
    assert read["version"] == 1, "GET never increments the version"

    suspended = validate_success(api_client.suspend_affiliate(aff["id"], ADMIN))
    assert suspended["version"] == 2

    reinstated = validate_success(api_client.reinstate_affiliate(aff["id"], ADMIN))
    assert reinstated["version"] == 3

    assert reinstated["created_at"] == aff["created_at"], (
        "created_at is stable across mutations"
    )
    assert reinstated["updated_at"] >= suspended["updated_at"]
    assert suspended["updated_at"] >= aff["updated_at"]


def test_mutations_visible_immediately_in_same_response(api):
    """PRD §3.5: "A `FrontDeskStaff` operator cancels a `SCHEDULED`
    encounter, transitioning clinical status to `CANCELLED`."

    The cancel response body itself shows clinical_status CANCELLED, and an
    immediate GET shows the identical state — no reconciliation lag.

    Design: Corner/consistency_model/mutations_visible_immediately_in_same_response
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    enc_id = ctx["encounter"]["id"]

    cancelled = validate_success(api_client.cancel_encounter(enc_id,
                                                             FRONT_DESK))
    assert cancelled["clinical_status"] == "CANCELLED", (
        "the mutation response body already shows the terminal state"
    )
    read_back = validate_success(api_client.get_encounter(enc_id, FRONT_DESK))
    assert read_back["clinical_status"] == "CANCELLED"
