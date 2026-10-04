"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_insurer_payload(**overrides) -> dict:
    defaults = {
        "insurer_code": _seq("INS"),
        "legal_name": "Test Member Mutual",
    }
    defaults.update(overrides)
    return defaults


def create_statistical_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": _seq("SP"),
        "line_of_business": TEST_DEFAULTS["LINE_OF_BUSINESS"],
        "min_premium_cents": 1,
        "max_record_age_months": 60,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(insurer_id, plan_id, **overrides) -> dict:
    defaults = {
        "insurer_id": insurer_id,
        "plan_id": plan_id,
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2026-01-01T00:00:00Z",
        "record_count": TEST_DEFAULTS["RECORD_COUNT"],
        "written_premium_cents": TEST_DEFAULTS["WRITTEN_PREMIUM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "edit_code": _seq("E"),
        "severity": "ERROR",
        "affected_records": 1,
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "department_name": "State Department of Insurance",
        "objection_window_days": TEST_DEFAULTS["OBJECTION_WINDOW_DAYS"],
        "max_lcm_deviation_pct": TEST_DEFAULTS["MAX_LCM_DEVIATION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(**overrides) -> dict:
    defaults = {
        "filing_code": _seq("LC"),
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "line_of_business": TEST_DEFAULTS["LINE_OF_BUSINESS"],
        "trend_selection": "LINEAR_LEAST_SQUARES",
        "effective_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cell_payload(**overrides) -> dict:
    defaults = {
        "class_code": _seq("C"),
        "earned_premium_cents": TEST_DEFAULTS["EARNED_PREMIUM_CENTS"],
        "incurred_loss_cents": TEST_DEFAULTS["INCURRED_LOSS_CENTS"],
        "weight_pct": TEST_DEFAULTS["WEIGHT_PCT"],
        "current_loss_cost_cents": TEST_DEFAULTS["CURRENT_LOSS_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_adoption_payload(insurer_id, filing_id, expected_filing_version, **overrides) -> dict:
    defaults = {
        "insurer_id": insurer_id,
        "filing_id": filing_id,
        "multiplier_pct": TEST_DEFAULTS["MULTIPLIER_PCT"],
        "expected_filing_version": expected_filing_version,
    }
    defaults.update(overrides)
    return defaults


def create_form_payload(**overrides) -> dict:
    defaults = {
        "form_number": _seq("CP-00"),
        "form_title": "Test Coverage Form",
        "form_kind": "POLICY_FORM",
    }
    defaults.update(overrides)
    return defaults


def create_variant_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CW",
        "variant_text_ref": _seq("txt/"),
        "effective_from": "2026-10-01T00:00:00Z",
        "effective_to": None,
    }
    defaults.update(overrides)
    return defaults


def create_circular_payload(**overrides) -> dict:
    defaults = {
        "circular_number": _seq("CIR-2026"),
        "subject": "Test circular",
        "implementation_date": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(insurer_id, **overrides) -> dict:
    defaults = {
        "insurer_id": insurer_id,
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2027-12-31T00:00:00Z",
        "royalty_rate_bps": TEST_DEFAULTS["ROYALTY_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_class_plan_payload(**overrides) -> dict:
    defaults = {
        "class_plan_code": _seq("CP-PLAN"),
        "line_of_business": TEST_DEFAULTS["LINE_OF_BUSINESS"],
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(**overrides) -> dict:
    defaults = {
        "class_count": 12,
        "activates_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
