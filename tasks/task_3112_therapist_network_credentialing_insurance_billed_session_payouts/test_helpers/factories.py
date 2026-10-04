"""Payload factories — one per entity, carrying only the fields the PRD
declares as client-supplied inputs."""
from .constants import DEFAULTS


def create_clinician_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLINICIAN_NAME"],
        "license_type": "LCSW",
        "primary_state": DEFAULTS["CLINICIAN_STATE"],
        "specialty_tags": ["ANXIETY"],
        "weekly_caseload_target": DEFAULTS["CASELOAD_TARGET"],
        "availability_blocks": [dict(block) for block in DEFAULTS["AVAILABILITY_BLOCKS"]],
    }
    payload.update(overrides)
    return payload


def create_license_payload(**overrides) -> dict:
    payload = {
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "license_type": "LCSW",
        "issuing_state": DEFAULTS["CLINICIAN_STATE"],
        "expires_on": DEFAULTS["LICENSE_EXPIRES_ON"],
        "telehealth_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_malpractice_policy_payload(**overrides) -> dict:
    payload = {
        "carrier_name": "TherapyGuard Mutual",
        "coverage_cents": DEFAULTS["COVERAGE_CENTS"],
        "effective_on": DEFAULTS["POLICY_EFFECTIVE_ON"],
        "expires_on": DEFAULTS["POLICY_EXPIRES_ON"],
        "tail_coverage": False,
    }
    payload.update(overrides)
    return payload


def create_payer_payload(**overrides) -> dict:
    payload = {
        "payer_name": DEFAULTS["PAYER_NAME"],
        "payer_code": DEFAULTS["PAYER_CODE"],
        "delegated_credentialing": True,
        "min_malpractice_coverage_cents": DEFAULTS["MIN_MALPRACTICE_COVERAGE_CENTS"],
        "timely_filing_days": DEFAULTS["TIMELY_FILING_DAYS"],
        "credentialing_sla_days": DEFAULTS["CREDENTIALING_SLA_DAYS"],
        "allowed_cpt_codes": list(DEFAULTS["ALLOWED_CPT_CODES"]),
    }
    payload.update(overrides)
    return payload


def create_payer_rate_payload(**overrides) -> dict:
    payload = {
        "rate_set_version": DEFAULTS["RATE_SET_VERSION"],
        "license_type": "LCSW",
        "geography": DEFAULTS["CLINICIAN_STATE"],
        "cpt_code": DEFAULTS["CPT_CODE"],
        "rate_cents": DEFAULTS["RATE_CENTS"],
        "effective_from": DEFAULTS["CONTRACT_RATE_EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def create_payer_enrollment_payload(**overrides) -> dict:
    payload = {
        "clinician_id": None,
        "payer_id": None,
        "delegated": True,
        "effective_from": DEFAULTS["ENROLLMENT_EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "member_id": DEFAULTS["MEMBER_ID"],
        "payer_id": None,
        "plan_code": DEFAULTS["PLAN_CODE"],
        "state_code": DEFAULTS["CLINICIAN_STATE"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
        "coinsurance_rate": DEFAULTS["COINSURANCE_RATE"],
        "oop_max_cents": DEFAULTS["OOP_MAX_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_verification_payload(**overrides) -> dict:
    payload = {
        "deductible_remaining_cents": DEFAULTS["VERIFICATION_DEDUCTIBLE_REMAINING_CENTS"],
        "coinsurance_rate": DEFAULTS["COINSURANCE_RATE"],
        "copay_cents": DEFAULTS["VERIFICATION_COPAY_CENTS"],
        "oop_remaining_cents": DEFAULTS["VERIFICATION_OOP_REMAINING_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_session_payload(**overrides) -> dict:
    payload = {
        "clinician_id": None,
        "patient_id": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "cpt_code": DEFAULTS["CPT_CODE"],
        "modality": DEFAULTS["MODALITY"],
    }
    payload.update(overrides)
    return payload


def create_session_note_payload(**overrides) -> dict:
    payload = {
        "diagnosis_code": DEFAULTS["DIAGNOSIS_CODE"],
        "duration_minutes": DEFAULTS["SESSION_MINUTES"],
        "cpt_code": DEFAULTS["CPT_CODE"],
        "narrative": DEFAULTS["NARRATIVE"],
        "expected_session_version": None,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(**overrides) -> dict:
    payload = {"session_id": None}
    payload.update(overrides)
    return payload


def create_payout_batch_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-06-08T00:00:00Z",
        "schedule": "WEEKLY",
    }
    payload.update(overrides)
    return payload


def create_continuity_plan_payload(**overrides) -> dict:
    payload = {
        "clinician_id": None,
        "patient_id": None,
        "reason": "OFFBOARDING",
    }
    payload.update(overrides)
    return payload