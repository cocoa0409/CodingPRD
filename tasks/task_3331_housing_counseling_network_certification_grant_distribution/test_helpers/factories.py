"""Payload factories — one per entity, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_counselor_email_seq = itertools.count(1)


def create_member_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Housing Org",
        "ein": "123456789",
        "state_code": "CA",
        "service_regions": ["06037"],
    }
    defaults.update(overrides)
    return defaults


def submit_assessment_payload(**overrides) -> dict:
    defaults = {
        "governance_score": 95,
        "finance_score": 95,
        "program_capacity_score": 95,
    }
    defaults.update(overrides)
    return defaults


def adjudicate_assessment_payload(**overrides) -> dict:
    defaults = {"site_visit_adjustment": 0}
    defaults.update(overrides)
    return defaults


def create_counselor_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "full_name": "Test Counselor",
        "email": f"counselor-{next(_counselor_email_seq)}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": "HO-100",
        "title": "Test Course",
        "program_area": "HOMEOWNERSHIP",
        "capacity": 5,
        "ce_eligible": False,
        "ce_credits": 0,
        "delivery_start": TEST_DEFAULTS["DEFAULT_DELIVERY_START"],
        "delivery_end": TEST_DEFAULTS["DEFAULT_DELIVERY_END"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "counselor_id": None,
        "program_area": "HOMEOWNERSHIP",
    }
    defaults.update(overrides)
    return defaults


def create_grant_cycle_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2030,
        "formula_pool_cents": 100000,
        "competitive_pool_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_grant_application_payload(**overrides) -> dict:
    defaults = {
        "cycle_id": None,
        "member_id": None,
        "program_area": "HOMEOWNERSHIP",
        "requested_formula_cents": 10000,
        "requested_competitive_cents": 0,
        "pledged_match_cents": 0,
        "expected_cycle_version": 1,
    }
    defaults.update(overrides)
    return defaults


def verify_match_payload(**overrides) -> dict:
    defaults = {"additional_match_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "award_id": None,
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_client_file_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "counselor_id": None,
        "program_area": "HOMEOWNERSHIP",
        "household_size": 2,
    }
    defaults.update(overrides)
    return defaults


def record_outcome_payload(**overrides) -> dict:
    defaults = {
        "outcome_code": "PURCHASED_HOME",
        "counseling_hours": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_file_review_payload(**overrides) -> dict:
    defaults = {"client_file_id": None}
    defaults.update(overrides)
    return defaults


def fail_file_review_payload(**overrides) -> dict:
    defaults = {"deficiency_codes": ["MISSING_BUDGET_WORKSHEET"]}
    defaults.update(overrides)
    return defaults


def create_expenditure_report_payload(**overrides) -> dict:
    defaults = {
        "award_id": None,
        "period_start": "2026-10-01T00:00:00Z",
        "period_end": "2026-10-31T00:00:00Z",
        "reported_spent_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def issue_findings_payload(**overrides) -> dict:
    defaults = {"disallowance_cents": 0}
    defaults.update(overrides)
    return defaults


def create_performance_review_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "review_period": "FY2030-H1",
    }
    defaults.update(overrides)
    return defaults
