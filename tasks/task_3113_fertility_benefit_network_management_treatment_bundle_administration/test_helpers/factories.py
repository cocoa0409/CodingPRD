"""Payload factories — one per resource, carrying only the fields the client supplies."""
from .constants import TEST_DEFAULTS

DEFAULTS = dict(TEST_DEFAULTS)


def create_employer_account_payload(**overrides) -> dict:
    payload = {
        "employer_name": "Test Employer",
        "plan_year": DEFAULTS["PLAN_YEAR"],
        "funding_type": "SELF_FUNDED",
        "allocation_method": "CONCURRENT_BUNDLE",
        "enrollment_limit": DEFAULTS["ENROLLMENT_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_bundle_entitlement_payload(employer_account_id: str, **overrides) -> dict:
    payload = {
        "employer_account_id": employer_account_id,
        "bundle_type": "IVF_RETRIEVAL_TRANSFER",
        "lifetime_max_cycles": DEFAULTS["LIFETIME_MAX_CYCLES"],
        "max_cycles_per_year": DEFAULTS["MAX_CYCLES_PER_YEAR"],
        "max_transfers_per_cycle": DEFAULTS["MAX_TRANSFERS_PER_CYCLE"],
        "pharmacy_pool_cents": DEFAULTS["PHARMACY_POOL_CENTS"],
        "copay_max": False,
        "effective_from": DEFAULTS["BUNDLE_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["BUNDLE_EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_care_advocate_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Advocate",
        "states_licensed": ["TX"],
        "specializations": ["STANDARD_IVF"],
        "caseload_limit": DEFAULTS["CASELOAD_LIMIT"],
        "credentials_expire_on": DEFAULTS["CREDENTIALS_EXPIRE_ON"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(employer_account_id: str, **overrides) -> dict:
    payload = {
        "employer_account_id": employer_account_id,
        "external_ref": "TEST-MEMBER-1",
        "full_name": "Test Member",
        "state_code": "TX",
        "required_track": "STANDARD_IVF",
    }
    payload.update(overrides)
    return payload


def create_clinic_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Test Clinic",
        "npi": "1000000001",
        "state_code": "TX",
        "network_tier": "PREFERRED",
        "min_live_birth_rate_bps": 0,
        "max_multiple_birth_rate_bps": 10000,
        "required_quality_report_count": 0,
        "maturity_report_threshold": DEFAULTS["MATURITY_REPORT_THRESHOLD"],
        "bundles_offered": ["IVF_RETRIEVAL_TRANSFER"],
    }
    payload.update(overrides)
    return payload


def create_clinic_contract_payload(**overrides) -> dict:
    payload = {
        "effective_from": DEFAULTS["BUNDLE_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["BUNDLE_EFFECTIVE_TO"],
        "bundle_rates": {"IVF_RETRIEVAL_TRANSFER": DEFAULTS["BUNDLE_RATE_IVF"]},
    }
    payload.update(overrides)
    return payload


def create_treatment_plan_payload(member_id: str, bundle_entitlement_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "bundle_entitlement_id": bundle_entitlement_id,
        "pathway_type": "STANDARD_IVF",
        "planned_cycles": 1,
    }
    payload.update(overrides)
    return payload


def create_preauthorization_payload(cycle_sequence_index: int = 1, **overrides) -> dict:
    payload = {
        "cycle_sequence_index": cycle_sequence_index,
        "criteria_inputs": {
            "age_years": 33,
            "amh_ng_ml": 2.0,
            "prior_cycles": 0,
            "prior_live_birth": False,
            "fsh_iu_l": 6,
        },
        "member_cost_share_pct": DEFAULTS["MEMBER_COST_SHARE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_treatment_cycle_payload(preauthorization_id: str, **overrides) -> dict:
    payload = {
        "preauthorization_id": preauthorization_id,
        "retrieval_date": "2026-09-05T00:00:00Z",
        "transfer_date": "2026-09-10T00:00:00Z",
        "embryos_transferred": 1,
    }
    payload.update(overrides)
    return payload


def create_cycle_outcome_payload(**overrides) -> dict:
    payload = {
        "live_birth": False,
        "births_count": 0,
        "multiple_birth": False,
        "gestational_weeks": 0,
    }
    payload.update(overrides)
    return payload


def create_clinic_outcome_payload(treatment_cycle_id: str, expected_treatment_cycle_version: int,
                                  **overrides) -> dict:
    payload = {
        "treatment_cycle_id": treatment_cycle_id,
        "live_birth": False,
        "births_count": 0,
        "multiple_birth": False,
        "gestational_weeks": 0,
        "expected_treatment_cycle_version": expected_treatment_cycle_version,
    }
    payload.update(overrides)
    return payload


def create_medication_order_payload(member_id: str, preauthorization_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "preauthorization_id": preauthorization_id,
        "medication_code": "GONAL-F-900",
        "specialty_drug": True,
        "quantity": 9,
        "days_supply": 12,
        "acquisition_cost_cents": 300000,
        "dispensing_pharmacy": "SP-TEST",
    }
    payload.update(overrides)
    return payload


def create_pathway_request_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "pathway_type": "PRESERVATION",
        "consent_signed": True,
        "consent_signed_on": "2026-08-20T00:00:00Z",
        "coverage_pct": 80,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(member_id: str, preauthorization_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "preauthorization_id": preauthorization_id,
        "service_category": "CLINIC_BUNDLE",
        "billed_cents": DEFAULTS["BUNDLE_RATE_IVF"],
        "service_date_iso": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_surrender_route_payload(expected_member_version: int, **overrides) -> dict:
    payload = {
        "pathway_type": "PRESERVATION",
        "carrier_kind": "CUSTODIAN",
        "route_from": "2026-09-01T00:00:00Z",
        "route_to": "2026-10-01T00:00:00Z",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload