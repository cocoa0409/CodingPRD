"""Payload factories -- one per resource, input fields only."""
from .constants import CLOCK_START, DEALER_DEFAULTS


def create_dealer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Ridgeline Motors",
        "state_code": "TX",
        "program_code": DEALER_DEFAULTS["PROGRAM_CODE"],
        "funding_line_cents": DEALER_DEFAULTS["FUNDING_LINE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(dealer_id, expected_dealer_version, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "participation_method": "RATE_PARTICIPATION",
        "max_participation_bps": 200,
        "chargeback_window_days": DEALER_DEFAULTS["CHARGEBACK_WINDOW_DAYS"],
        "effective_from": "2026-02-01T00:00:00Z",
        "effective_to": "2027-02-01T00:00:00Z",
        "expected_dealer_version": expected_dealer_version,
    }
    payload.update(overrides)
    return payload


def create_rate_sheet_payload(**overrides) -> dict:
    payload = {
        "program_code": DEALER_DEFAULTS["PROGRAM_CODE"],
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# The three-band price list used throughout: richest band first.
TIER_T1 = {
    "tier_code": "T1", "min_credit_score": 720, "max_credit_score": 900,
    "max_ltv_pct": 120, "max_term_months": 72, "buy_rate_apr_bps": 549,
    "advance_rate_pct": 120, "acquisition_fee_cents": 15000,
}
TIER_T2 = {
    "tier_code": "T2", "min_credit_score": 660, "max_credit_score": 719,
    "max_ltv_pct": 115, "max_term_months": 72, "buy_rate_apr_bps": 749,
    "advance_rate_pct": 115, "acquisition_fee_cents": 20000,
}
TIER_T3 = {
    "tier_code": "T3", "min_credit_score": 600, "max_credit_score": 659,
    "max_ltv_pct": 110, "max_term_months": 60, "buy_rate_apr_bps": 1099,
    "advance_rate_pct": 110, "acquisition_fee_cents": 30000,
}
STANDARD_TIERS = [TIER_T1, TIER_T2, TIER_T3]


def create_tier_payload(**overrides) -> dict:
    payload = dict(TIER_T1)
    payload.update(overrides)
    return payload


def create_application_payload(dealer_id, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "applicant_reference": "APP-001",
        "monitoring_cohort": "CONTROL",
        "credit_score": 725,
        "monthly_income_cents": 600000,
        "monthly_debt_cents": 210000,
        "amount_financed_cents": 2801000,
        "collateral_value_cents": 2500000,
        "term_months": 60,
        "vehicle_model_year": 2024,
        "requested_apr_bps": 749,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "contract_apr_bps": 749,
        "contract_date": CLOCK_START,
    }
    payload.update(overrides)
    return payload


def create_document_payload(doc_type, document_reference=None, **overrides) -> dict:
    payload = {
        "doc_type": doc_type,
        "document_reference": document_reference or f"IMG-{doc_type[:6]}",
    }
    payload.update(overrides)
    return payload


def create_scorecard_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-12-01T00:00:00Z",
        "basis": "TRAILING_WINDOW",
    }
    payload.update(overrides)
    return payload


def create_review_payload(dealer_id, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_reserve_adjustment_payload(amount_cents, expected_dealer_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "reason": "OPENING_RESERVE_BALANCE",
        "expected_dealer_version": expected_dealer_version,
    }
    payload.update(overrides)
    return payload
