"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Corp",
        "pepm_fee_cents": 1000,
        "avg_in_out_cost_delta_cents": 200000,
        "emo_benefit_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "date_of_birth": "1985-01-01",
        "relationship": "SELF",
        "external_member_ref": "REF-1",
        "deductible_limit_cents": TEST_DEFAULTS["DEDUCTIBLE_LIMIT_CENTS"],
        "oop_max_cents": TEST_DEFAULTS["OOP_MAX_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_coverage_window_payload(**overrides) -> dict:
    defaults = {
        "coverage_tier": "EMPLOYEE_ONLY",
        "effective_start": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Clinic",
        "specialty": "GENERAL",
        "network_status": "IN_NETWORK",
    }
    defaults.update(overrides)
    return defaults


def create_quality_snapshot_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
        "outcome_score": 80,
        "cost_efficiency_score": 60,
        "access_score": 90,
        "claims_volume": 40,
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    defaults = {
        "scope": "APPOINTMENT_BOOKING",
        "expires_at": TEST_DEFAULTS["FAR_FUTURE_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_navigation_case_payload(**overrides) -> dict:
    defaults = {
        "question_type": "BENEFIT",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "provider_id": None,
        "slot_start": "2026-09-05T10:00:00Z",
        "slot_end": "2026-09-05T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_record_request_payload(**overrides) -> dict:
    defaults = {
        "provider_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_expert_opinion_payload(**overrides) -> dict:
    defaults = {
        "condition_summary": "Second opinion requested",
    }
    defaults.update(overrides)
    return defaults


def claim_line(line_code="A", billed_cents=10000, schedule_rate=1.0,
               error_flag="NONE") -> dict:
    return {
        "line_code": line_code,
        "billed_cents": billed_cents,
        "schedule_rate": schedule_rate,
        "error_flag": error_flag,
    }


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "provider_id": None,
        "service_date": "2026-08-01",
        "billed_amount_cents": 100000,
        "allowed_amount_cents": 90000,
        "lines": [claim_line()],
    }
    defaults.update(overrides)
    return defaults


def create_billing_case_payload(**overrides) -> dict:
    defaults = {
        "claim_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(**overrides) -> dict:
    defaults = {
        "service_code": "PROCEDURE",
        "units": 1,
    }
    defaults.update(overrides)
    return defaults
