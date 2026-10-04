"""Payload factories for every resource the platform accepts."""
from .constants import (
    FUTURE_LICENSE_EXPIRES_ON,
    FUTURE_LOCK_EXPIRES_AT,
    STANDARD_LOAN_AMOUNT_CENTS,
    STANDARD_PLAN_BORROWER_PAID_CENTS,
    STANDARD_PLAN_LENDER_PAID_CENTS,
    STANDARD_VOLUME_EXPECTATION_CENTS,
)

DEFAULTS = {
    "LEGAL_NAME": "Test Wholesale Brokerage LLC",
    "HOME_STATE": "TX",
    "VOLUME_EXPECTATION_CENTS": STANDARD_VOLUME_EXPECTATION_CENTS,
    "LICENSE_TYPE": "MORTGAGE_BROKER",
    "LOAN_AMOUNT_CENTS": STANDARD_LOAN_AMOUNT_CENTS,
    "BORROWER_NAME": "Test Borrower",
    "PLAN_LENDER_PAID_CENTS": STANDARD_PLAN_LENDER_PAID_CENTS,
    "PLAN_BORROWER_PAID_CENTS": STANDARD_PLAN_BORROWER_PAID_CENTS,
}

_NMLS_SEQUENCE = {"n": 0}


def next_nmls_id(prefix: str = "NMLS-9") -> str:
    """A distinct NMLS identifier, so no accidental uniqueness collision."""
    _NMLS_SEQUENCE["n"] += 1
    return f"{prefix}{_NMLS_SEQUENCE['n']:05d}"


def broker_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "nmls_id": next_nmls_id(),
        "home_state": DEFAULTS["HOME_STATE"],
        "volume_expectation_cents": DEFAULTS["VOLUME_EXPECTATION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def license_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["HOME_STATE"],
        "license_number": "TX-MB-0001",
        "license_type": DEFAULTS["LICENSE_TYPE"],
        "expires_on": FUTURE_LICENSE_EXPIRES_ON,
    }
    defaults.update(overrides)
    return defaults


def financial_review_payload(**overrides) -> dict:
    defaults = {
        "net_worth_cents": 100_000_000,
        "liquidity_cents": 40_000_000,
        "total_liabilities_cents": 0,
        "years_in_business": 5,
        "prior_year_funded_volume_cents": 100_000_000,
        "audit_attested": True,
    }
    defaults.update(overrides)
    return defaults


def product_eligibility_payload(**overrides) -> dict:
    defaults = {
        "product_code": "CONVENTIONAL",
        "max_ltv": 0.9500,
        "min_fico": 620,
        "max_loan_amount_cents": 200_000_000,
    }
    defaults.update(overrides)
    return defaults


def exclusivity_policy_payload(broker_id: str, **overrides) -> dict:
    defaults = {
        "broker_id": broker_id,
        "competitor_identifier": "COMP-ALPHA",
        "competitor_name": "Alpha Mortgage Partners",
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2026-12-01T00:00:00Z",
        "status": "ACTIVE",
        "restriction_scope": "LOAN_SUBMISSION",
    }
    defaults.update(overrides)
    return defaults


def compensation_plan_payload(broker_id: str, **overrides) -> dict:
    defaults = {
        "broker_id": broker_id,
        "plan_code": "PLAN_A",
        "default_election": "LENDER_PAID",
        "lender_paid_amount_cents": DEFAULTS["PLAN_LENDER_PAID_CENTS"],
        "borrower_paid_amount_cents": DEFAULTS["PLAN_BORROWER_PAID_CENTS"],
        "is_active": True,
    }
    defaults.update(overrides)
    return defaults


def standard_adjustment_table(**overrides) -> list:
    """The four-row table used by most pricing fixtures."""
    return overrides.get(
        "table",
        [
            {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
            {"dim": "ltv", "bucket": "up-to-60", "adjust_pct": 0.000},
            {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
            {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
        ],
    )


def rate_sheet_payload(**overrides) -> dict:
    defaults = {
        "product_code": "CONVENTIONAL",
        "base_rate_pct": 6.125,
        "adjustment_table": standard_adjustment_table(),
    }
    defaults.update(overrides)
    return defaults


def pricing_quote_payload(**overrides) -> dict:
    defaults = {
        "representative_fico": 780,
        "ltv_ratio": 0.5500,
        "occupancy_type": "PRIMARY_RESIDENCE",
        "loan_amount_cents": DEFAULTS["LOAN_AMOUNT_CENTS"],
        "lock_period_days": 30,
        "loan_purpose": "PURCHASE",
    }
    defaults.update(overrides)
    return defaults


def loan_submission_payload(broker_id: str, pricing_quote_id: str, **overrides) -> dict:
    defaults = {
        "broker_id": broker_id,
        "pricing_quote_id": pricing_quote_id,
        "borrower_name": DEFAULTS["BORROWER_NAME"],
        "property_state": DEFAULTS["HOME_STATE"],
        "loan_amount_cents": DEFAULTS["LOAN_AMOUNT_CENTS"],
        "lock_expires_at": FUTURE_LOCK_EXPIRES_AT,
    }
    defaults.update(overrides)
    return defaults


def underwriting_decision_payload(loan_id: str, **overrides) -> dict:
    defaults = {
        "loan_submission_id": loan_id,
        "decision_type": "CONDITIONAL",
        "conditions": ["final title commitment"],
        "decision_notes": "conditional approval",
    }
    defaults.update(overrides)
    return defaults


def quality_control_review_payload(loan_id: str, **overrides) -> dict:
    defaults = {
        "loan_submission_id": loan_id,
        "defect_type": "NON_DEFECT",
        "severity": "MINOR",
        "remediation_status": "NONE",
    }
    defaults.update(overrides)
    return defaults