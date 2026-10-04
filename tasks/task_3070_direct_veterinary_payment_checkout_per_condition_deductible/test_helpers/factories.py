"""Payload factories — one per creatable entity, input fields only."""
from .constants import TEST_DEFAULTS, TERRITORY_CODE, STATE_CODE


def create_rate_filing_payload(**overrides) -> dict:
    defaults = {
        "territory_code": TERRITORY_CODE,
        "state_code": STATE_CODE,
        "species": "DOG",
        "base_monthly_premium_cents": TEST_DEFAULTS["BASE_MONTHLY_PREMIUM_CENTS"],
        "age_band_multipliers": {"0": 1.0, "1": 1.0025},
        "filing_effective_date": "2026-09-01",
        "regulator_reference": "CA-2026-001",
    }
    defaults.update(overrides)
    return defaults


def create_hospital_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Sunset Vet",
        "territory_code": TERRITORY_CODE,
        "bank_account_ref": "BA-001",
        "checkout_software_version": "1.2.3",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "owner_name": "Ana Reyes",
        "pet_name": "Miso",
        "species": "DOG",
        "breed": "Shiba",
        "pet_date_of_birth": TEST_DEFAULTS["PET_DATE_OF_BIRTH"],
        "territory_code": TERRITORY_CODE,
        "coverage_start": TEST_DEFAULTS["COVERAGE_START"],
        "per_condition_deductible_cents": TEST_DEFAULTS["PER_CONDITION_DEDUCTIBLE_CENTS"],
        "reimbursement_rate": TEST_DEFAULTS["REIMBURSEMENT_RATE"],
    }
    defaults.update(overrides)
    return defaults


def treatment_line(amount_cents=50000, condition_code="DXA", description="treatment"):
    return {
        "description": description,
        "amount_cents": amount_cents,
        "category": "TREATMENT",
        "condition_code": condition_code,
    }


def create_claim_payload(policy_id, hospital_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "hospital_id": hospital_id,
        "visit_date": "2026-10-02",
        "claim_type": "INJURY",
        "lines": [treatment_line()],
    }
    defaults.update(overrides)
    return defaults


def create_medical_record_payload(hospital_id, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "record_type": "EXAM",
        "recorded_at": "2026-10-02T09:00:00Z",
        "diagnosis_code": "DXA",
        "notes": "annual",
    }
    defaults.update(overrides)
    return defaults
