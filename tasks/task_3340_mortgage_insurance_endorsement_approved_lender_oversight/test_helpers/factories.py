"""Payload factories — one per entity, input fields only."""
from .constants import STANDARD_CASE, STANDARD_FILING

_lender_seq = [0]
_case_seq = [0]


def _next(seq: list) -> int:
    seq[0] += 1
    return seq[0]


def lender_payload(**overrides) -> dict:
    n = _next(_lender_seq)
    defaults = {
        "legal_name": f"Test Lender {n}",
        "institution_type": "MORTGAGEE_SUPERVISED",
        "home_state": "VA",
        "qc_plan_on_file": True,
    }
    defaults.update(overrides)
    return defaults


def filing_payload(lender_version: int, **overrides) -> dict:
    defaults = dict(STANDARD_FILING)
    defaults["expected_lender_version"] = lender_version
    defaults.update(overrides)
    return defaults


def filing_decision_payload(lender_version: int, decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision, "expected_lender_version": lender_version}
    payload.update(overrides)
    return payload


def loan_case_payload(lender_id: str, **overrides) -> dict:
    n = _next(_case_seq)
    defaults = dict(STANDARD_CASE)
    defaults["lender_id"] = lender_id
    defaults["borrower_reference"] = f"BOR-{n:04d}"
    defaults.update(overrides)
    return defaults


def appraisal_payload(**overrides) -> dict:
    defaults = {
        "appraised_value_cents": 31_250_000,
        "effective_date": "2026-07-01",
    }
    defaults.update(overrides)
    return defaults


def escrow_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 500_000,
        "start_date": "2026-09-01",
        "end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def review_payload(**overrides) -> dict:
    defaults = {"scope_codes": ["UNDERWRITING"]}
    defaults.update(overrides)
    return defaults


def defect_payload(**overrides) -> dict:
    defaults = {"defect_code": "ASSET_VERIFICATION_MISSING", "detail": "finding detail"}
    defaults.update(overrides)
    return defaults


def agreement_payload(**overrides) -> dict:
    defaults = {"coverage_cap_cents": 1_000_000}
    defaults.update(overrides)
    return defaults


def loss_mitigation_payload(action_type: str = "REPAYMENT_PLAN", **overrides) -> dict:
    payload = {"action_type": action_type}
    payload.update(overrides)
    return payload


def claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "CONVEYANCE",
        "unpaid_principal_balance_cents": 30_000_000,
        "expense_items": [],
    }
    defaults.update(overrides)
    return defaults
