"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_seller_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Meridian Lending",
        "seller_number": _seq("S"),
        "net_worth_cents": TEST_DEFAULTS["SELLER_NET_WORTH_CENTS"],
        "qc_defect_rate_bps": TEST_DEFAULTS["SELLER_QC_DEFECT_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_servicer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Atlas Servicing",
        "servicer_number": _seq("V"),
        "net_worth_cents": TEST_DEFAULTS["SERVICER_NET_WORTH_CENTS"],
        "qc_rating": "SATISFACTORY",
    }
    defaults.update(overrides)
    return defaults


def create_master_agreement_payload(seller_id, servicer_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "servicer_id": servicer_id,
        "effective_date": "2026-01-01T00:00:00Z",
        "expiration_date": "2028-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def standard_llpa_row(**overrides) -> dict:
    defaults = {
        "occupancy": "PRIMARY_RESIDENCE",
        "product_type": "FIXED_30",
        "llpa_bps": 100,
        "ltv_min_bp": 0,
        "ltv_max_bp": 9500,
        "credit_min": 620,
        "credit_max": 850,
    }
    defaults.update(overrides)
    return defaults


def create_llpa_matrix_payload(rows=None, **overrides) -> dict:
    defaults = {
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_until": "2027-01-01T00:00:00Z",
        "rows": rows if rows is not None else [standard_llpa_row()],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(seller_id, servicer_id, agreement_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "servicer_id": servicer_id,
        "agreement_id": agreement_id,
        "loan_number": _seq("LN"),
        "borrower_name": "Alex Chen",
        "unpaid_principal_balance_cents": TEST_DEFAULTS["LOAN_UPB_CENTS"],
        "appraised_value_cents": TEST_DEFAULTS["LOAN_APPRAISAL_CENTS"],
        "credit_score": TEST_DEFAULTS["LOAN_CREDIT_SCORE"],
        "occupancy": "PRIMARY_RESIDENCE",
        "product_type": "FIXED_30",
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(seller_id, agreement_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "agreement_id": agreement_id,
        "pool_number": _seq("PL"),
        "issue_date": "2026-10-01T00:00:00Z",
        "target_balance_cents": TEST_DEFAULTS["POOL_TARGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_event_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "due_date": "2026-10-01T00:00:00Z",
        "paid_on_time": True,
        "amount_cents": TEST_DEFAULTS["PAYMENT_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_qc_audit_payload(seller_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "sampling_method": "RANDOM",
    }
    defaults.update(overrides)
    return defaults


def create_qc_finding_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "defect_category": "COLLATERAL",
        "severity": "SIGNIFICANT",
    }
    defaults.update(overrides)
    return defaults


def create_servicing_transfer_payload(loan_id, to_servicer_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "to_servicer_id": to_servicer_id,
        "effective_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_subservicer_oversight_payload(servicer_id, subservicer_id, **overrides) -> dict:
    defaults = {
        "servicer_id": servicer_id,
        "subservicer_id": subservicer_id,
        "oversight_period_start": "2026-06-01T00:00:00Z",
        "oversight_period_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
