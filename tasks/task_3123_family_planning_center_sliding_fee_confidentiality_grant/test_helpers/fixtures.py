"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted server with an empty database,
so each fixture builds its entire precondition chain from scratch using only
PRD-declared endpoints. Uses get_success_data() (lenient validator) so setup
failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_affiliate_payload,
    create_catalog_entry_payload,
    create_fee_tier_payload,
    create_patient_payload,
    create_assessment_payload,
    create_provider_payload,
    create_license_payload,
    create_encounter_payload,
    create_stock_lot_payload,
    create_device_reservation_payload,
    create_referral_payload,
    create_grant_report_payload,
    create_privacy_hold_payload,
)
from .constants import (
    CLOCK_START,
    ENC_START,
    ENC_END,
    LARC_START,
    LARC_END,
    REPORT_PERIOD_START,
    REPORT_PERIOD_END,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_headers"]
CARE = TEST_USERS["care_coordinator_headers"]
SUPPLY = TEST_USERS["supply_coordinator_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: atomic resource helpers
# ---------------------------------------------------------------------------

def set_clock(iso_ts=CLOCK_START):
    """Advance the logical clock. Returns the clock response data."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso_ts}, ADMIN))


def create_affiliate(**overrides):
    """Create an affiliate. Returns the affiliate dict (ACTIVE, version 1)."""
    return get_success_data(
        api_client.create_affiliate(create_affiliate_payload(**overrides), ADMIN),
        201,
    )


def create_catalog_entry(affiliate_id, **overrides):
    return get_success_data(
        api_client.create_catalog_entry(
            affiliate_id, create_catalog_entry_payload(**overrides), ADMIN
        ),
        201,
    )


def create_fee_tier(affiliate_id, **overrides):
    return get_success_data(
        api_client.create_fee_tier(
            affiliate_id, create_fee_tier_payload(**overrides), ADMIN
        ),
        201,
    )


def create_patient(affiliate_id, **overrides):
    return get_success_data(
        api_client.create_patient(
            affiliate_id, create_patient_payload(**overrides), FRONT_DESK
        ),
        201,
    )


def create_assessment(patient, **overrides):
    """Create a household assessment for a patient dict (threads OCC version).

    `patient` is the patient dict; its current version is used as
    expected_patient_version unless overridden.
    """
    payload = create_assessment_payload(**overrides)
    payload.setdefault("expected_patient_version", patient["version"])
    return get_success_data(
        api_client.create_assessment(patient["id"], payload, FRONT_DESK),
        201,
    )


def get_patient(patient_id):
    return get_success_data(api_client.get_patient(patient_id, FRONT_DESK))


def create_provider(affiliate_id, **overrides):
    return get_success_data(
        api_client.create_provider(
            affiliate_id, create_provider_payload(**overrides), ADMIN
        ),
        201,
    )


def create_license(provider_id, **overrides):
    return get_success_data(
        api_client.create_license(
            provider_id, create_license_payload(**overrides), ADMIN
        ),
        201,
    )


def create_encounter(patient_id, provider_id, **overrides):
    return get_success_data(
        api_client.create_encounter(
            patient_id, create_encounter_payload(provider_id, **overrides), FRONT_DESK
        ),
        201,
    )


def create_stock_lot(affiliate_id, **overrides):
    return get_success_data(
        api_client.create_stock_lot(
            affiliate_id, create_stock_lot_payload(**overrides), SUPPLY
        ),
        201,
    )


def create_device_reservation(encounter_id, lot_id, **overrides):
    return get_success_data(
        api_client.create_device_reservation(
            encounter_id, create_device_reservation_payload(lot_id, **overrides), SUPPLY
        ),
        201,
    )


def get_stock_lot(lot_id):
    return get_success_data(api_client.get_stock_lot(lot_id, SUPPLY))


def get_encounter(encounter_id):
    return get_success_data(api_client.get_encounter(encounter_id, FRONT_DESK))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, BILLING))


def get_grant_report(report_id):
    return get_success_data(api_client.get_grant_report(report_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: standard configuration scenarios
# ---------------------------------------------------------------------------

def create_affiliate_with_tiers_abcd(quota=50, **aff_overrides):
    """Affiliate + the canonical four-tier fee schedule used by depth tests.

    Tiers: A=[0,100) disc 100 copay 500 doc-only; B=[0,150) disc 80 copay 500;
    C=[150,200) disc 50 copay 0; D=[200,1000) disc 0 copay 0.
    Returns (affiliate, tiers dict keyed by tier_code).
    """
    aff = create_affiliate(low_income_priority_quota=quota, **aff_overrides)
    tiers = {
        "A": create_fee_tier(
            aff["id"], tier_code="A", fpl_pct_min_inclusive=0,
            fpl_pct_max_exclusive=100, discount_pct=100,
            nominal_copay_cents=500, requires_documentation=True,
        ),
        "B": create_fee_tier(
            aff["id"], tier_code="B", fpl_pct_min_inclusive=0,
            fpl_pct_max_exclusive=150, discount_pct=80,
            nominal_copay_cents=500, requires_documentation=False,
        ),
        "C": create_fee_tier(
            aff["id"], tier_code="C", fpl_pct_min_inclusive=150,
            fpl_pct_max_exclusive=200, discount_pct=50,
            nominal_copay_cents=0, requires_documentation=False,
        ),
        "D": create_fee_tier(
            aff["id"], tier_code="D", fpl_pct_min_inclusive=200,
            fpl_pct_max_exclusive=1000, discount_pct=0,
            nominal_copay_cents=0, requires_documentation=False,
        ),
    }
    return aff, tiers


def setup_tx_clinic(quota=50, service_code="CONTRACEPTIVE_COUNSELING",
                    full_fee_cents=20000, telehealth_eligible=True,
                    license_state="TX", license_valid_from="2026-01-01T00:00:00Z",
                    license_valid_until="2027-01-01T00:00:00Z",
                    tiers="abcd"):
    """Full standard clinic: clock set, affiliate + tiers + catalog + licensed provider.

    Returns dict with keys: affiliate, tiers (or None), catalog, provider, license.
    """
    set_clock(CLOCK_START)
    if tiers == "abcd":
        aff, tier_map = create_affiliate_with_tiers_abcd(quota=quota)
    elif tiers == "d":
        aff = create_affiliate(low_income_priority_quota=quota)
        tier_map = {"D": create_fee_tier(aff["id"])}
    else:
        aff = create_affiliate(low_income_priority_quota=quota)
        tier_map = None
    catalog = create_catalog_entry(
        aff["id"], service_code=service_code,
        full_fee_cents=full_fee_cents, telehealth_eligible=telehealth_eligible,
    )
    provider = create_provider(aff["id"])
    license_ = create_license(
        provider["id"], state_code=license_state,
        valid_from=license_valid_from, valid_until=license_valid_until,
    )
    return {
        "affiliate": aff,
        "tiers": tier_map,
        "catalog": catalog,
        "provider": provider,
        "license": license_,
    }


def setup_patient_with_assessment(clinic, income_cents=4000000, household_size=1,
                                  income_basis="DOCUMENTED", **patient_overrides):
    """Create a patient under the clinic's affiliate and record an assessment.

    Returns (patient_after_assessment, assessment). The patient dict is
    re-fetched so its version reflects the assessment bump.
    """
    patient = create_patient(clinic["affiliate"]["id"], **patient_overrides)
    assessment = create_assessment(
        patient, household_size=household_size,
        annual_income_cents=income_cents, income_basis=income_basis,
    )
    return get_patient(patient["id"]), assessment


def setup_assessed_encounter(clinic, income_cents=4000000, household_size=1,
                             income_basis="DOCUMENTED",
                             enc_start=ENC_START, enc_end=ENC_END,
                             service_code=None, channel="IN_PERSON",
                             patient_location_state=None,
                             **patient_overrides):
    """Patient + assessment + one SCHEDULED encounter. Returns dict of the three."""
    patient, assessment = setup_patient_with_assessment(
        clinic, income_cents=income_cents, household_size=household_size,
        income_basis=income_basis, **patient_overrides
    )
    enc_kwargs = {}
    if service_code is not None:
        enc_kwargs["service_code"] = service_code
    if patient_location_state is not None:
        enc_kwargs["patient_location_state"] = patient_location_state
    encounter = create_encounter(
        patient["id"], clinic["provider"]["id"],
        scheduled_start=enc_start, scheduled_end=enc_end,
        channel=channel, **enc_kwargs,
    )
    return {"patient": patient, "assessment": assessment, "encounter": encounter}


def setup_completed_encounter(clinic, clock_at_start="2026-09-10T10:00:00Z",
                              **kwargs):
    """Like setup_assessed_encounter, but the encounter is started + completed.

    Advances the logical clock to `clock_at_start` before starting.
    Returns dict with patient, assessment, encounter (COMPLETED).
    """
    ctx = setup_assessed_encounter(clinic, **kwargs)
    set_clock(clock_at_start)
    get_success_data(api_client.start_encounter(ctx["encounter"]["id"], CLINICIAN))
    ctx["encounter"] = get_success_data(
        api_client.complete_encounter(ctx["encounter"]["id"], CLINICIAN)
    )
    return ctx


def setup_submitted_claim(clinic, **kwargs):
    """Completed encounter + DRAFT claim + submitted claim.

    Returns dict with patient, assessment, encounter, claim (SUBMITTED).
    """
    ctx = setup_completed_encounter(clinic, **kwargs)
    claim = get_success_data(
        api_client.create_claim(ctx["encounter"]["id"], BILLING), 201
    )
    ctx["claim"] = get_success_data(api_client.submit_claim(claim["id"], BILLING))
    ctx["encounter"] = get_encounter(ctx["encounter"]["id"])
    return ctx
