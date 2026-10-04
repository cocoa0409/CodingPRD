"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

# Sequence counters so server-side uniqueness constraints (borrower email,
# school code, product code) never collide inside a single test.
_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_borrower_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "full_name": "Test Borrower",
        "email": f"borrower{n}@example.com",
        "state_code": "VT",
        "program_level": "UNDERGRADUATE",
        "credit_score": TEST_DEFAULTS["BORROWER_SCORE"],
        "dti_ratio": TEST_DEFAULTS["BORROWER_DTI"],
    }
    payload.update(overrides)
    return payload


def create_cosigner_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "full_name": "Test Cosigner",
        "email": f"cosigner{n}@example.com",
        "state_code": "VT",
        "relationship": "PARENT",
        "credit_score": TEST_DEFAULTS["COSIGNER_SCORE"],
        "credit_history_months": 168,
        "dti_ratio": TEST_DEFAULTS["COSIGNER_DTI"],
    }
    payload.update(overrides)
    return payload


def create_school_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "name": "Test College",
        "school_code": f"{300000 + n:06d}",
        "state_code": "VT",
        "certification_capacity_per_period_cents": TEST_DEFAULTS["SCHOOL_CAPACITY_CENTS"],
        "active": True,
    }
    payload.update(overrides)
    return payload


def create_policy_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "product_code": f"SM-TEST-{n:04d}",
        "program_level": "UNDERGRADUATE",
        "extended_term_months": 180,
        "cosigner_release_min_on_time_payments": 24,
        "capitalized_interest_cap_pct": 0.10,
        "in_school_max_deferment_months": 48,
        "repayment_max_deferment_months": 24,
        "delinquency_notice_threshold_days": 5,
        "allows_standalone_borrower": False,
    }
    payload.update(overrides)
    return payload


def create_application_payload(
    borrower_id: str,
    school_id: str,
    policy_id: str,
    cosigner_id=None,
    **overrides,
) -> dict:
    payload = {
        "borrower_id": borrower_id,
        "school_id": school_id,
        "policy_id": policy_id,
        "requested_amount_cents": TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
        "cost_of_attendance_cents": TEST_DEFAULTS["COST_OF_ATTENDANCE_CENTS"],
        "other_aid_cents": TEST_DEFAULTS["OTHER_AID_CENTS"],
        "interest_accrual_option": "DEFERRED",
        "repayment_term_months": TEST_DEFAULTS["REPAYMENT_TERM_MONTHS"],
    }
    if cosigner_id is not None:
        payload["cosigner_id"] = cosigner_id
    payload.update(overrides)
    return payload


def certification_request_payload(**overrides) -> dict:
    payload = {
        "academic_period_label": "2026-FALL",
        "certified_amount_cents": TEST_DEFAULTS["CERTIFIED_AMOUNT_CENTS"],
        "certified_enrollment_status": "IN_SCHOOL",
        "period_end_date": "2026-12-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def certify_payload(**overrides) -> dict:
    payload = {
        "certified_amount_cents": TEST_DEFAULTS["CERTIFIED_AMOUNT_CENTS"],
        "certified_enrollment_status": "IN_SCHOOL",
    }
    payload.update(overrides)
    return payload


def disbursement_payload(**overrides) -> dict:
    payload = {
        "academic_period_label": "2026-FALL",
        "period_start_date": "2026-09-02T00:00:00Z",
        "period_end_date": "2026-12-20T00:00:00Z",
        "scheduled_date": "2026-09-15T00:00:00Z",
        "amount_cents": TEST_DEFAULTS["DISBURSEMENT_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def repayment_plan_payload(expected_loan_version, **overrides) -> dict:
    payload = {
        "plan_type": "STANDARD",
        "term_months": TEST_DEFAULTS["REPAYMENT_TERM_MONTHS"],
        "expected_loan_version": expected_loan_version,
    }
    payload.update(overrides)
    return payload


def payment_payload(due_period_index: int, paid_date: str, **overrides) -> dict:
    payload = {
        "due_period_index": due_period_index,
        "paid_date": paid_date,
        "amount_cents": TEST_DEFAULTS["PERIOD_PAYMENT_CENTS"],
    }
    payload.update(overrides)
    return payload


def forbearance_payload(**overrides) -> dict:
    payload = {
        "relief_type": "ECONOMIC_HARDSHIP_FORBEARANCE",
        "months_requested": 3,
        "interest_treatment": "ACCRUES_UNPAID",
        "start_date": "2026-11-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def release_application_payload(cosigner_id: str, **overrides) -> dict:
    payload = {
        "cosigner_id": cosigner_id,
        "independent_credit_score": 690,
        "independent_dti_ratio": 0.30,
    }
    payload.update(overrides)
    return payload