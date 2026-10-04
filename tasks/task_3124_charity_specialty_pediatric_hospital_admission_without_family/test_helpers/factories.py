"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HOSPITAL_CODE": "H1",
    "HOSPITAL_NAME": "Hospital One",
    "CITY": "Portland",
    "STATE_CODE": "OR",
    "HOSPITAL_LAT": 45.0,
    "HOSPITAL_LON": -122.0,
    "ANNUAL_CAPACITY": 5,
    "CATEGORY": "ORTHOPEDIC",
    "MIN_AGE_MONTHS": 0,
    "MAX_AGE_MONTHS": 215,
    "SOURCE_TYPE": "COMMUNITY_PHYSICIAN",
    "DISPLAY_NAME": "Dr. Rivera",
    "CONTACT_EMAIL": "rivera@example.org",
    "COUNTRY_CODE": "US",
    "PATIENT_NAME": "Kid One",
    "PATIENT_DOB": "2020-01-01T00:00:00Z",
    "HOME_LAT": 45.0,
    "HOME_LON": -121.0,
    "PAYER_NAME": "PayerCo",
    "POLICY_NUMBER": "POL-1",
    "SERVICE_DATE": "2026-09-02T00:00:00Z",
    "CPT_CODE": "99213",
    "CHARGE_CENTS": 1000,
    "DIAGNOSIS_SUMMARY": "Test diagnosis",
    "PLANNED_STAGE_COUNT": 1,
    "STAGE_INDEX": 1,
    "STAGE_MIN_AGE": 60,
    "STAGE_MAX_AGE": 120,
    "STAGE_DATE": "2026-10-01T00:00:00Z",
    "STAGE_COST": 200000,
    "GRANT_TYPE": "TRAVEL_AND_LODGING",
    "CLINIC_NAME": "Pendleton",
    "CLINIC_LAT": 45.67,
    "CLINIC_LON": -118.79,
    "CLINIC_START": "2026-10-01T00:00:00Z",
    "CLINIC_END": "2026-10-02T00:00:00Z",
    "CLINIC_CAPACITY": 2,
    "SCREENING_NAME": "Scout One",
    "SCREENING_DOB": "2019-05-01T00:00:00Z",
    "SCREENING_DATE": "2026-10-01T00:00:00Z",
    "FUND_NAME": "General Fund",
    "FISCAL_YEAR": 2026,
    "TOTAL_COMMITTED_CENTS": 100000,
    "ALLOCATION_CENTS": 5000,
}


def create_hospital_payload(**overrides) -> dict:
    defaults = {
        "hospital_code": DEFAULTS["HOSPITAL_CODE"],
        "name": DEFAULTS["HOSPITAL_NAME"],
        "city": DEFAULTS["CITY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "latitude": DEFAULTS["HOSPITAL_LAT"],
        "longitude": DEFAULTS["HOSPITAL_LON"],
        "annual_capacity": DEFAULTS["ANNUAL_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "category": DEFAULTS["CATEGORY"],
        "accepts_international": False,
        "min_age_months": DEFAULTS["MIN_AGE_MONTHS"],
        "max_age_months": DEFAULTS["MAX_AGE_MONTHS"],
        "staged_care_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_referral_source_payload(**overrides) -> dict:
    defaults = {
        "source_type": DEFAULTS["SOURCE_TYPE"],
        "display_name": DEFAULTS["DISPLAY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(referral_source_id, program_id, **overrides) -> dict:
    defaults = {
        "patient_full_name": DEFAULTS["PATIENT_NAME"],
        "patient_date_of_birth": DEFAULTS["PATIENT_DOB"],
        "condition_category": DEFAULTS["CATEGORY"],
        "referral_source_id": referral_source_id,
        "program_id": program_id,
        "home_latitude": DEFAULTS["HOME_LAT"],
        "home_longitude": DEFAULTS["HOME_LON"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "payer_name": DEFAULTS["PAYER_NAME"],
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "coverage_exists": True,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["SERVICE_DATE"],
        "lines": [{
            "cpt_code": DEFAULTS["CPT_CODE"],
            "charge_cents": DEFAULTS["CHARGE_CENTS"],
        }],
    }
    defaults.update(overrides)
    return defaults


def create_staged_procedure_payload(**overrides) -> dict:
    defaults = {
        "stage_index": DEFAULTS["STAGE_INDEX"],
        "min_age_months": DEFAULTS["STAGE_MIN_AGE"],
        "max_age_months": DEFAULTS["STAGE_MAX_AGE"],
        "scheduled_date": DEFAULTS["STAGE_DATE"],
        "estimated_cost_cents": DEFAULTS["STAGE_COST"],
    }
    defaults.update(overrides)
    return defaults


def create_outreach_clinic_payload(**overrides) -> dict:
    defaults = {
        "location_name": DEFAULTS["CLINIC_NAME"],
        "latitude": DEFAULTS["CLINIC_LAT"],
        "longitude": DEFAULTS["CLINIC_LON"],
        "start_date": DEFAULTS["CLINIC_START"],
        "end_date": DEFAULTS["CLINIC_END"],
        "screening_capacity": DEFAULTS["CLINIC_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    defaults = {
        "patient_full_name": DEFAULTS["SCREENING_NAME"],
        "patient_date_of_birth": DEFAULTS["SCREENING_DOB"],
        "suspected_condition_category": DEFAULTS["CATEGORY"],
        "screening_date": DEFAULTS["SCREENING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_name": DEFAULTS["FUND_NAME"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "total_committed_cents": DEFAULTS["TOTAL_COMMITTED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(hospital_id, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "amount_cents": DEFAULTS["ALLOCATION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def vote_payload(vote="ACCEPT", vote_weight=1, **overrides) -> dict:
    payload = {"vote": vote, "vote_weight": vote_weight}
    payload.update(overrides)
    return payload


def decide_payload(decision="ACCEPT", decision_reason="ok", expected_application_version=1,
                   **overrides) -> dict:
    payload = {
        "decision": decision,
        "decision_reason": decision_reason,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload
