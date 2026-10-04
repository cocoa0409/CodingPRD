"""Payload factories — one per entity, declared input fields only."""

from .constants import TEST_DEFAULTS as D


def create_fund_payload(**overrides) -> dict:
    payload = {
        "fund_code": D["FUND_CODE"],
        "fiscal_year": D["FISCAL_YEAR"],
        "fundraising_raised_cents": D["RAISED_CENTS"],
        "research_allocation_pct": D["RESEARCH_ALLOCATION_PCT"],
        "federal_grant_cents": D["FEDERAL_GRANT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_donation_payload(**overrides) -> dict:
    payload = {"amount_cents": 20_000_000, "is_federal_grant": False}
    payload.update(overrides)
    return payload


def create_protocol_payload(fund_id: str, **overrides) -> dict:
    payload = {
        "fund_id": fund_id,
        "protocol_code": D["PROTOCOL_CODE"],
        "disease_group": D["DISEASE_GROUP"],
        "age_min_years": D["AGE_MIN_YEARS"],
        "age_max_years": D["AGE_MAX_YEARS"],
        "required_stage": D["REQUIRED_STAGE"],
        "protocol_budget_cents": D["PROTOCOL_BUDGET_CENTS"],
        "capacity": D["CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "facility_code": D["FACILITY_ON_CAMPUS_CODE"],
        "name": D["FACILITY_ON_CAMPUS_NAME"],
        "tier": "ON_CAMPUS",
        "total_beds": 4,
        "buffer_beds": 0,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(protocol_id: str, **overrides) -> dict:
    payload = {
        "protocol_id": protocol_id,
        "child_name": D["CHILD_NAME"],
        "child_date_of_birth": D["CHILD_DOB"],
        "disease_group": D["DISEASE_GROUP"],
        "disease_stage": D["REQUIRED_STAGE"],
        "household_state_code": D["HOUSEHOLD_STATE"],
        "traveling_family_member_count": D["TRAVELING_COUNT"],
        "expected_treatment_days": D["EXPECTED_DAYS"],
        "is_immunosuppressed": False,
        "insurance_coverage_cents": D["INSURANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_consent_payload(**overrides) -> dict:
    payload = {
        "consent_signer": "GUARDIAN_AND_CHILD",
        "guardian_consent_signature_code": D["GUARDIAN_SIGNATURE"],
        "child_assent_signature_code": D["CHILD_SIGNATURE"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(enrollment_id: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "start_at": "2026-09-01T00:00:00Z",
        "end_at": "2026-09-02T00:00:00Z",
        "buffer_window_days": 1,
    }
    payload.update(overrides)
    return payload


def create_pledge_payload(enrollment_id: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "patient_support_budget_cents": D["PATIENT_SUPPORT_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_travel_payload(**overrides) -> dict:
    payload = {
        "mode": "AIR_ECONOMY",
        "traveler_count": 2,
        "departure_at": "2026-09-05T00:00:00Z",
        "return_at": "2026-09-06T00:00:00Z",
        "trip_reason": "PROTOCOL_REVIEW",
        "is_required_travel": True,
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(**overrides) -> dict:
    payload = {
        "milestone_sequence": 1,
        "description": "Induction",
        "requires_main_campus": True,
        "target_at": "2026-09-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_clinic_payload(**overrides) -> dict:
    payload = {
        "clinic_code": "AF-TN-01",
        "name": "Memphis Affiliate",
        "state_code": "TN",
        "is_active": True,
    }
    payload.update(overrides)
    return payload


def create_affiliation_payload(protocol_id: str, **overrides) -> dict:
    payload = {
        "protocol_id": protocol_id,
        "protocol_version": "v1",
        "effective_start_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_study_payload(**overrides) -> dict:
    payload = {
        "study_code": "SURV-001",
        "follow_up_interval_months": 12,
        "min_years_after_completion": 5,
    }
    payload.update(overrides)
    return payload


def create_service_payload(fund_id: str, **overrides) -> dict:
    payload = {
        "fund_id": fund_id,
        "service_code": "MEALS",
        "display_name": "Meals A",
        "base_allowance_cents": 20_000,
        "is_stimulation_eligible": True,
        "stimulation_rate": 0.3,
        "stimulation_cap_cents": 5_000,
    }
    payload.update(overrides)
    return payload


def create_sibling_payload(**overrides) -> dict:
    payload = {
        "sibling_alias": "R-Sib",
        "service_type": "SIBLING_CAMP",
        "delivery_window_start_at": "2026-09-01T00:00:00Z",
        "delivery_window_end_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_hold_payload(**overrides) -> dict:
    payload = {"hold_reason": "IRB_REVIEW", "initiated_at": "2026-09-02T00:00:00Z"}
    payload.update(overrides)
    return payload