"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dana Ruiz",
        "employee_number": "EMP-2201",
        "department_code": TEST_DEFAULTS["DEPARTMENT_CODE"],
        "pre_injury_weekly_wage_cents": TEST_DEFAULTS["PRE_INJURY_WEEKLY_WAGE_CENTS"],
        "pre_injury_weekly_hours": TEST_DEFAULTS["PRE_INJURY_WEEKLY_HOURS"],
        "benefit_tier": "TIER_B",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_number": "CLM-2201",
        "adjuster_user_id": "adj-001",
        "injury_date": "2026-06-15",
    }
    defaults.update(overrides)
    return defaults


def adjuster_authorization_payload(**overrides) -> dict:
    defaults = {
        "max_authorized_weekly_cost_cents": TEST_DEFAULTS["CLAIM_CEILING_CENTS"],
        "claim_status_directive": "RTW_ELIGIBLE",
    }
    defaults.update(overrides)
    return defaults


def create_treating_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Imani Okafor",
        "npi": "1234567890",
        "specialty": "Occupational Medicine",
        "credential_status": "VERIFIED",
    }
    defaults.update(overrides)
    return defaults


def create_restriction_set_payload(treating_provider_id, expected_claim_version, **overrides) -> dict:
    defaults = {
        "treating_provider_id": treating_provider_id,
        "expected_claim_version": expected_claim_version,
        "effective_from": TEST_DEFAULTS["RESTRICTION_EFFECTIVE_FROM"],
        "valid_through": TEST_DEFAULTS["RESTRICTION_VALID_THROUGH"],
        "max_lift_lbs": 20,
        "max_continuous_standing_minutes": 30,
        "max_hours_per_day": 6,
        "keyboard_minutes_per_hour": 45,
        "overhead_reach_allowed": False,
        "driving_allowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_supervisor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Sam Ortiz",
        "department_code": TEST_DEFAULTS["DEPARTMENT_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "curriculum_code": "RTW_CORE",
        "completed_on": "2026-05-01",
        "valid_through": "2027-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_transitional_job_payload(supervisor_id, **overrides) -> dict:
    defaults = {
        "supervisor_id": supervisor_id,
        "title": "Parts Sorter",
        "department_code": TEST_DEFAULTS["DEPARTMENT_CODE"],
        "seat_capacity": 2,
        "demand_lift_lbs": 10,
        "demand_standing_minutes": 15,
        "demand_hours_per_day": 4,
        "demand_keyboard_minutes_per_hour": 20,
        "hourly_rate_cents": TEST_DEFAULTS["JOB_HOURLY_RATE_CENTS"],
        "risk_class": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(restriction_set_id, transitional_job_id,
                             expected_restriction_set_version, **overrides) -> dict:
    defaults = {
        "restriction_set_id": restriction_set_id,
        "transitional_job_id": transitional_job_id,
        "start_date": TEST_DEFAULTS["PLACEMENT_START_DATE"],
        "end_date": TEST_DEFAULTS["PLACEMENT_END_DATE"],
        "scheduled_hours_per_day": TEST_DEFAULTS["SCHEDULED_HOURS_PER_DAY"],
        "expected_restriction_set_version": expected_restriction_set_version,
    }
    defaults.update(overrides)
    return defaults


def auto_match_payload(restriction_set_id, expected_restriction_set_version, **overrides) -> dict:
    defaults = {
        "restriction_set_id": restriction_set_id,
        "start_date": TEST_DEFAULTS["PLACEMENT_START_DATE"],
        "end_date": TEST_DEFAULTS["PLACEMENT_END_DATE"],
        "scheduled_hours_per_day": TEST_DEFAULTS["SCHEDULED_HOURS_PER_DAY"],
        "expected_restriction_set_version": expected_restriction_set_version,
    }
    defaults.update(overrides)
    return defaults


def decide_directive_payload(**overrides) -> dict:
    defaults = {
        "decision": "AUTHORIZED",
        "authorized_weekly_cost_cents": TEST_DEFAULTS["AUTHORIZED_WEEKLY_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def compliance_audit_payload(**overrides) -> dict:
    defaults = {
        "observed_on": "2026-08-01",
        "finding_severity": "MINOR",
        "finding_code": "DOCUMENTATION",
    }
    defaults.update(overrides)
    return defaults


def reinjury_report_payload(**overrides) -> dict:
    defaults = {
        "occurred_on": "2026-08-04",
        "severity": "MINOR",
        "body_part_code": "LUMBAR",
        "mechanism_code": "LIFT_STRAIN",
    }
    defaults.update(overrides)
    return defaults


def case_review_payload(**overrides) -> dict:
    defaults = {"trigger_reason": "COMPLIANCE_CRITICAL", "quorum_required": 3}
    defaults.update(overrides)
    return defaults


def vote_payload(ballot, expected_case_review_version, **overrides) -> dict:
    defaults = {
        "ballot": ballot,
        "expected_case_review_version": expected_case_review_version,
    }
    defaults.update(overrides)
    return defaults


def wage_entry_payload(**overrides) -> dict:
    defaults = {
        "variant": "PROVISIONAL",
        "period_start": "2026-08-03",
        "period_end": "2026-08-07",
    }
    defaults.update(overrides)
    return defaults


def hours_log_payload(**overrides) -> dict:
    defaults = {"work_date": "2026-08-03", "hours_worked": 4}
    defaults.update(overrides)
    return defaults
