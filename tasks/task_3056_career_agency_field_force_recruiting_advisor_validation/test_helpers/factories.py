"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS, PASSING_COMPETENCIES


def district_office_payload(**overrides) -> dict:
    defaults = {
        "office_code": TEST_DEFAULTS["OFFICE_CODE"],
        "name": TEST_DEFAULTS["OFFICE_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def advisor_payload(office_id, **overrides) -> dict:
    defaults = {
        "full_name": "Test Advisor",
        "email": "test.advisor@agency.example",
        "district_office_id": office_id,
        "rank": "REP",
    }
    defaults.update(overrides)
    return defaults


def candidate_payload(office_id, **overrides) -> dict:
    defaults = {
        "full_name": "Test Candidate",
        "source_channel": "REFERRAL",
        "district_office_id": office_id,
    }
    defaults.update(overrides)
    return defaults


def schedule_assessment_payload(assessment_version="V2", scheduled_date=None) -> dict:
    return {
        "assessment_version": assessment_version,
        "scheduled_date": scheduled_date or TEST_DEFAULTS["CANDIDATE_SCHEDULED_DATE"],
    }


def score_payload(competency_scores=None, raw_score=85) -> dict:
    return {
        "raw_score": raw_score,
        "competency_scores": dict(competency_scores or PASSING_COMPETENCIES),
    }


def employment_contract_payload(advisor_id, candidate_id, expected_candidate_version,
                                **overrides) -> dict:
    defaults = {
        "advisor_id": advisor_id,
        "candidate_id": candidate_id,
        "contract_type": "FULL_TIME",
        "start_date": TEST_DEFAULTS["CONTRACT_START_DATE"],
        "training_allowance_total_cents": TEST_DEFAULTS["ALLOWANCE_TOTAL_1200000"],
        "training_allowance_mode": "PRODUCTION_DRAW",
        "validation_requirement_cents": TEST_DEFAULTS["REQUIREMENT_300000"],
        "expected_candidate_version": expected_candidate_version,
    }
    defaults.update(overrides)
    return defaults


def validation_period_payload(contract_id, expected_contract_version, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "period_number": 1,
        "start_date": "2026-01-08T00:00:00Z",
        "end_date": "2026-12-31T00:00:00Z",
        "required_production_cents": 100000,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def product_license_payload(advisor_id, **overrides) -> dict:
    defaults = {
        "advisor_id": advisor_id,
        "product_line": "LIFE",
        "license_number": "WI-LIFE-0001",
        "effective_date": TEST_DEFAULTS["LEGACY_START"],
        "expires_at": TEST_DEFAULTS["LEGACY_EXPIRY"],
        "appointment_required": True,
    }
    defaults.update(overrides)
    return defaults


def securities_registration_payload(advisor_id, **overrides) -> dict:
    defaults = {
        "advisor_id": advisor_id,
        "registration_type": "SERIES_66",
        "crd_number": "CRD-0001",
        "effective_date": TEST_DEFAULTS["LEGACY_START"],
        "expires_at": TEST_DEFAULTS["LEGACY_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def carrier_appointment_payload(advisor_id, requires_license_id, **overrides) -> dict:
    defaults = {
        "advisor_id": advisor_id,
        "requires_license_id": requires_license_id,
        "carrier_name": "Northwestern Mutual",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "requested_date": "2026-01-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def policy_payload(writing_advisor_id, **overrides) -> dict:
    defaults = {
        "policy_number": "NM-T0001",
        "writing_advisor_id": writing_advisor_id,
        "carrier_name": "Northwestern Mutual",
        "product_line": "LIFE",
        "annual_premium_cents": TEST_DEFAULTS["PREMIUM_480000"],
        "issue_date": "2026-02-01T00:00:00Z",
        "is_advanced_commission": True,
    }
    defaults.update(overrides)
    return defaults


def joint_work_case_payload(policy_id, lead_advisor_id, support_advisor_id,
                            expected_policy_version, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "lead_advisor_id": lead_advisor_id,
        "support_advisor_id": support_advisor_id,
        "split_pct_lead": 0.6,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def persistency_record_payload(advisor_id, **overrides) -> dict:
    defaults = {
        "advisor_id": advisor_id,
        "measurement_period": "2026-H1",
        "measurement_start": "2026-01-01T00:00:00Z",
        "measurement_end": "2026-06-30T00:00:00Z",
        "policies_issued": 20,
        "policies_persisted": 20,
    }
    defaults.update(overrides)
    return defaults