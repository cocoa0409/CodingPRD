"""Depth tests: cross-entity state dependencies."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_tx_clinic, setup_assessed_encounter,
    create_affiliate_with_tiers_abcd, create_catalog_entry,
    create_provider, create_license, create_patient, create_assessment,
    set_clock,
    TEST_USERS, FPL_INCOME_H1_PCT_174, FPL_INCOME_H1_PCT_265,
    ENC_START, ENC_END,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_expired_license_blocks_telehealth_encounter_creation(api):
    """PRD §2.5: "Setting the clock re-derives two families of derived state:
    `ProviderLicense` rows whose `valid_until` now precedes the new logical
    time transition to `EXPIRED`".
    PRD §3.4: "The delivering provider must hold a `ProviderLicense` whose
    `state_code` equals the encounter's `patient_location_state`, whose
    status is `ACTIVE` ... Failure is rejected with
    `ERR_TELEHEALTH_LICENSE_GAP` (HTTP 422)."

    A license valid at setup time becomes EXPIRED after the clock advances
    past valid_until; encounter creation against it is rejected.

    Design: Difficulty/cross_entity_state_dependency/telehealth_encounter_gated_by_license_derived_state
    """
    set_clock("2026-09-01T00:00:00Z")
    aff, _tiers = create_affiliate_with_tiers_abcd(quota=50)
    create_catalog_entry(aff["id"], service_code="CONTRACEPTIVE_COUNSELING",
                         in_scope=True, telehealth_eligible=True,
                         full_fee_cents=20000)
    provider = create_provider(aff["id"], display_name="Dr. Expiring",
                               provider_type="NP")
    license_ = create_license(provider["id"], state_code="TX",
                              valid_from="2026-01-01T00:00:00Z",
                              valid_until="2026-06-01T00:00:00Z")
    patient = create_patient_helper(aff["id"])
    set_clock("2026-09-10T00:00:00Z")

    lic_after = validate_success(
        api_client.get_license(license_["id"], FRONT_DESK)
    )
    assert lic_after["status"] == "EXPIRED", (
        f"license EXPIRED is derived from the logical clock, got "
        f"{lic_after['status']}"
    )

    res = api_client.create_encounter(
        patient["id"],
        {
            "service_code": "CONTRACEPTIVE_COUNSELING",
            "provider_id": provider["id"],
            "channel": "TELEHEALTH",
            "patient_location_state": "TX",
            "scheduled_start": "2026-09-11T10:00:00Z",
            "scheduled_end": "2026-09-11T10:30:00Z",
        },
        FRONT_DESK,
    )
    validate_error(res, "ERR_TELEHEALTH_LICENSE_GAP", expected_status=422)


def test_expired_license_rejection_persists_no_encounter(api):
    """PRD §3.4: "The delivering provider must hold a `ProviderLicense` whose
    `state_code` equals the encounter's `patient_location_state`, whose
    status is `ACTIVE`, whose `valid_from` is less than or equal to the
    encounter's `scheduled_start`, and whose `valid_until` is greater than or
    equal to the encounter's `scheduled_end`."
    PRD §2.5: "`ProviderLicense` rows whose `valid_until` now precedes the
    new logical time transition to `EXPIRED`".

    The license-gapped telehealth creation leaves zero encounters behind.

    Design: Difficulty/cross_entity_state_dependency/telehealth_encounter_gated_by_license_derived_state
    """
    set_clock("2026-09-01T00:00:00Z")
    aff, _tiers = create_affiliate_with_tiers_abcd(quota=50)
    create_catalog_entry(aff["id"], service_code="CONTRACEPTIVE_COUNSELING",
                         in_scope=True, telehealth_eligible=True,
                         full_fee_cents=20000)
    provider = create_provider(aff["id"], display_name="Dr. Expiring2",
                               provider_type="NP")
    create_license(provider["id"], state_code="TX",
                   valid_from="2026-01-01T00:00:00Z",
                   valid_until="2026-06-01T00:00:00Z")
    patient = create_patient_helper(aff["id"])
    set_clock("2026-09-10T00:00:00Z")

    res = api_client.create_encounter(
        patient["id"],
        {
            "service_code": "CONTRACEPTIVE_COUNSELING",
            "provider_id": provider["id"],
            "channel": "TELEHEALTH",
            "patient_location_state": "TX",
            "scheduled_start": "2026-09-11T10:00:00Z",
            "scheduled_end": "2026-09-11T10:30:00Z",
        },
        FRONT_DESK,
    )
    validate_error(res, "ERR_TELEHEALTH_LICENSE_GAP", expected_status=422)
    rows, meta = validate_paginated(
        api_client.list_patient_encounters(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 0
    assert meta["total_count"] == 0


def create_patient_helper(affiliate_id):
    """Adult patient with a DOCUMENTED tier-D assessment. Returns patient."""
    patient = create_patient(affiliate_id, external_ref="X1",
                             date_of_birth="1990-01-01")
    create_assessment(patient, household_size=1,
                      annual_income_cents=FPL_INCOME_H1_PCT_265,
                      income_basis="DOCUMENTED")
    return patient


def test_claim_creation_rejected_on_in_progress_encounter(api):
    """PRD §3.7: "When a completed encounter remains in billing status
    `UNBILLED`, a `BillingSpecialist` may open a `Claim` against it."
    PRD §3.7: "the preconditions are that the parent encounter's clinical
    status is `COMPLETED` and the claim's `confidential_suppression` is
    `false`".

    Opening a claim while the encounter is still IN_PROGRESS is a 409
    ERR_INVALID_STATE — claim creation is gated on the parent's clinical
    axis reaching COMPLETED.

    Design: Difficulty/cross_entity_state_dependency/claim_creation_gated_by_encounter_clinical_state
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-X2",
    )
    enc_id = ctx["encounter"]["id"]
    set_clock("2026-09-10T10:00:00Z")
    validate_success(api_client.start_encounter(enc_id, CLINICIAN))

    res = api_client.create_claim(enc_id, BILLING)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    enc_after = validate_success(api_client.get_encounter(enc_id, FRONT_DESK))
    assert enc_after["billing_status"] == "UNBILLED", (
        "billing untouched by the rejected claim creation"
    )


def test_rejected_claim_creation_persists_no_claim(api):
    """PRD §3.7: "When a completed encounter remains in billing status
    `UNBILLED`, a `BillingSpecialist` may open a `Claim` against it."

    A claim creation attempted against an IN_PROGRESS encounter persists no
    claim rows at all.

    Design: Difficulty/cross_entity_state_dependency/claim_creation_gated_by_encounter_clinical_state
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-X3",
    )
    enc_id = ctx["encounter"]["id"]
    set_clock("2026-09-10T10:00:00Z")
    validate_success(api_client.start_encounter(enc_id, CLINICIAN))

    res = api_client.create_claim(enc_id, BILLING)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    rows, meta = validate_paginated(api_client.list_claims(enc_id, BILLING))
    assert len(rows) == 0
    assert meta["total_count"] == 0
