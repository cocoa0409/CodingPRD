"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULTS


def employer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "fein": DEFAULTS["FEIN"],
        "employer_type": DEFAULTS["EMPLOYER_TYPE"],
        "payroll_frequency": DEFAULTS["PAYROLL_FREQUENCY"],
    }
    payload.update(overrides)
    return payload


def worker_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["WORKER_NAME"],
        "ssn_last4": DEFAULTS["WORKER_SSN_LAST4"],
        "date_of_birth": DEFAULTS["WORKER_DOB"],
    }
    payload.update(overrides)
    return payload


def layout_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "layout_version": 1,
        "column_map": dict(DEFAULTS["COMPLETE_COLUMN_MAP"]),
        "fiscal_year_start_month": 1,
    }
    payload.update(overrides)
    return payload


def incomplete_layout_payload(employer_id, **overrides) -> dict:
    """A layout map missing the pay_rate_basis canonical field."""
    column_map = dict(DEFAULTS["COMPLETE_COLUMN_MAP"])
    column_map.pop("BASIS")
    payload = {
        "employer_id": employer_id,
        "layout_version": 1,
        "column_map": column_map,
        "fiscal_year_start_month": 1,
    }
    payload.update(overrides)
    return payload


def batch_payload(employer_id, layout_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "record_layout_id": layout_id,
        "batch_sequence": 1,
        "pay_period_end_date": DEFAULTS["PAY_PERIOD_END"],
        "record_count": DEFAULTS["BATCH_RECORD_COUNT"],
    }
    payload.update(overrides)
    return payload


def record_payload(employer_id, worker_id, batch_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "covered_worker_id": worker_id,
        "payroll_feed_batch_id": batch_id,
        "employment_status": "ACTIVE",
        "hire_date": DEFAULTS["HIRE_DATE"],
        "separation_date": None,
        "pay_rate_cents": DEFAULTS["PAY_RATE_CENTS"],
        "pay_rate_basis": DEFAULTS["PAY_RATE_BASIS"],
        "standard_hours_per_week": DEFAULTS["STANDARD_HOURS_PER_WEEK"],
        "final_pay_period_income_cents": 0,
    }
    payload.update(overrides)
    return payload


def product_payload(**overrides) -> dict:
    payload = {
        "product_code": DEFAULTS["PRODUCT_CODE"],
        "tier": DEFAULTS["PRODUCT_TIER"],
        "requesting_class": DEFAULTS["PRODUCT_REQUESTING_CLASS"],
        "base_fee_cents": DEFAULTS["PRODUCT_BASE_FEE_CENTS"],
        "history_months_included": DEFAULTS["PRODUCT_HISTORY_MONTHS"],
        "includes_employment_status": True,
    }
    payload.update(overrides)
    return payload


def verifier_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["VERIFIER_NAME"],
        "verifier_class": DEFAULTS["VERIFIER_CLASS"],
        "permitted_purpose": DEFAULTS["VERIFIER_PURPOSE"],
        "escrow_balance_cents": DEFAULTS["VERIFIER_ESCROW_CENTS"],
    }
    payload.update(overrides)
    return payload


def authorization_payload(worker_id, verifier_id, worker_version, **overrides) -> dict:
    payload = {
        "covered_worker_id": worker_id,
        "verifier_id": verifier_id,
        "permitted_purpose": DEFAULTS["VERIFIER_PURPOSE"],
        "expected_covered_worker_version": worker_version,
    }
    payload.update(overrides)
    return payload


def request_payload(verifier_id, worker_id, product_id, **overrides) -> dict:
    payload = {
        "verifier_id": verifier_id,
        "covered_worker_id": worker_id,
        "product_id": product_id,
        "permissible_purpose_asserted": DEFAULTS["VERIFIER_PURPOSE"],
    }
    payload.update(overrides)
    return payload


def dispute_payload(record_id, worker_id, record_version, **overrides) -> dict:
    payload = {
        "employment_record_id": record_id,
        "covered_worker_id": worker_id,
        "claimed_field": "EMPLOYMENT_STATUS",
        "claimed_correct_value": "TERMINATED",
        "expected_employment_record_version": record_version,
    }
    payload.update(overrides)
    return payload


def accrual_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "pay_period_end_date": DEFAULTS["PAY_PERIOD_END"],
        "transaction_ref": "txn-1",
        "records_count": 1200,
    }
    payload.update(overrides)
    return payload


def settlement_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "settlement_period_end": "2026-06-30T00:00:00Z",
        "settlement_budget_cents": 12000,
        "waiver_budget_cents": 0,
    }
    payload.update(overrides)
    return payload


def review_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "review_period_end": "2026-06-30T00:00:00Z",
        "window_days": 30,
        "last_feed_date_in_window": "2026-06-29T00:00:00Z",
        "distinct_pay_periods_in_window": 4,
        "expected_periods": 4,
    }
    payload.update(overrides)
    return payload