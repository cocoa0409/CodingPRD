"""Entity construction with common-field defaults."""
import clock
import store
from domain import (
    AUTHORIZATION_VALIDITY_DAYS, DISPUTE_RESPONSE_WINDOW_DAYS, REQUIRED_CANONICAL_FIELDS,
)


def entity(timestamp=None):
    ts = timestamp or clock.now()
    return {"id": store.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


class ApiError(Exception):
    pass


def new_employer(body):
    row = entity()
    row.update({
        "legal_name": body.get("legal_name"),
        "fein": body.get("fein"),
        "employer_type": body.get("employer_type"),
        "payroll_frequency": body.get("payroll_frequency"),
        "feed_status": "CURRENT",
        "last_feed_received_date": None,
        "freeze_state": "NONE",
        "freeze_reason_code": None,
        "freeze_requested_at": None,
        "review_state": "NONE",
        "review_period_end": None,
        "missing_periods": 0,
        "currency_score": 0,
        "total_records_contributed": 0,
        "dispute_open_count": 0,
        "compensation_earned_cents": 0,
        "counted_verification_records": 0,
    })
    return row


def layout_diagnostics(column_map):
    targets = set()
    for value in (column_map or {}).values():
        targets.add(value)
    missing = sorted(name for name in REQUIRED_CANONICAL_FIELDS if name not in targets)
    return len(missing), missing


def new_record_layout(body):
    row = entity()
    column_map = body.get("column_map") or {}
    count, missing = layout_diagnostics(column_map)
    row.update({
        "employer_id": body.get("employer_id"),
        "layout_version": body.get("layout_version"),
        "column_map": column_map,
        "fiscal_year_start_month": body.get("fiscal_year_start_month"),
        "status": "DRAFT",
        "verified_at": None,
        "validation_error_count": count,
        "missing_canonical_fields": missing,
    })
    return row


def new_payroll_feed_batch(body):
    row = entity()
    row.update({
        "employer_id": body.get("employer_id"),
        "record_layout_id": body.get("record_layout_id"),
        "batch_sequence": body.get("batch_sequence"),
        "pay_period_end_date": clock.parse_iso(body.get("pay_period_end_date")),
        "received_at": clock.now(),
        "record_count": body.get("record_count"),
        "accepted_record_count": 0,
        "rejected_record_count": 0,
        "gross_amount_cents": 0,
        "validation_state": "RECEIVED",
    })
    return row


def new_employment_record(body):
    row = entity()
    row.update({
        "employer_id": body.get("employer_id"),
        "covered_worker_id": body.get("covered_worker_id"),
        "payroll_feed_batch_id": body.get("payroll_feed_batch_id"),
        "employment_status": body.get("employment_status"),
        "hire_date": clock.parse_iso(body.get("hire_date")),
        "separation_date": clock.parse_iso(body.get("separation_date")),
        "pay_rate_cents": body.get("pay_rate_cents"),
        "pay_rate_basis": body.get("pay_rate_basis"),
        "standard_hours_per_week": body.get("standard_hours_per_week"),
        "final_pay_period_income_cents": body.get("final_pay_period_income_cents", 0),
        "record_state": "PENDING_VERIFICATION",
        "currency_state": "CURRENT",
        "annualized_income_cents": 0,
        "tenure_months": 0,
        "frozen_by_employer_version": None,
    })
    return row


def new_covered_worker(body):
    row = entity()
    row.update({
        "full_name": body.get("full_name"),
        "ssn_last4": body.get("ssn_last4"),
        "date_of_birth": clock.parse_iso(body.get("date_of_birth")),
        "consent_status": "PROVIDED",
        "opt_out": False,
        "disclosure_state": "NEVER_DISCLOSED",
        "open_dispute_count": 0,
        "corrected_record_count": 0,
    })
    return row


def new_verifier(body):
    row = entity()
    row.update({
        "legal_name": body.get("legal_name"),
        "verifier_class": body.get("verifier_class"),
        "permitted_purpose": body.get("permitted_purpose"),
        "entitlement_status": "UNVERIFIED",
        "posture": "RESTRICTED",
        "escrow_balance_cents": body.get("escrow_balance_cents", 0) or 0,
        "transaction_count": 0,
        "negative_escalation_count": 0,
    })
    return row


def new_verification_product(body):
    row = entity()
    row.update({
        "product_code": body.get("product_code"),
        "tier": body.get("tier"),
        "requesting_class": body.get("requesting_class"),
        "base_fee_cents": body.get("base_fee_cents"),
        "history_months_included": body.get("history_months_included"),
        "includes_employment_status": body.get("includes_employment_status"),
        "active": body.get("active", True),
        "rendered_field_set": [],
    })
    return row


def new_consumer_authorization(body):
    row = entity()
    granted_at = clock.now()
    row.update({
        "covered_worker_id": body.get("covered_worker_id"),
        "verifier_id": body.get("verifier_id"),
        "permitted_purpose": body.get("permitted_purpose"),
        "granted_at": granted_at,
        "expires_at": clock.add_days(granted_at, AUTHORIZATION_VALIDITY_DAYS),
        "revoked_at": None,
        "status": "CAPTURED",
    })
    return row


def new_verification_request(body):
    row = entity()
    row.update({
        "verifier_id": body.get("verifier_id"),
        "covered_worker_id": body.get("covered_worker_id"),
        "product_id": body.get("product_id"),
        "consumer_authorization_id": None,
        "permissible_purpose_asserted": body.get("permissible_purpose_asserted"),
        "submitted_at": clock.now(),
        "request_state": "SUBMITTED",
        "decline_reason": None,
        "resolved_product_tier": None,
        "current_employer_id": None,
        "current_employment_status": None,
        "current_tenure_months": None,
        "rendered_field_set": [],
        "records_matched_count": 0,
        "responded_at": None,
        "fee_charged_cents": 0,
    })
    return row


def new_verification_response(body):
    row = {"id": store.new_id(), "created_at": clock.now()}
    row.update({
        "verification_request_id": body.get("verification_request_id"),
        "product_tier": body.get("product_tier"),
        "rendered_fields": body.get("rendered_fields", []),
        "employment_status": body.get("employment_status"),
        "tenure_months": body.get("tenure_months"),
        "income_history": body.get("income_history", []),
        "active_employment_found": body.get("active_employment_found", False),
        "employer_feed_status": body.get("employer_feed_status"),
    })
    return row


def new_consumer_disclosure(body):
    row = entity()
    row.update({
        "covered_worker_id": body.get("covered_worker_id"),
        "requested_at": clock.now(),
        "disclosure_state": "REQUESTED",
        "included_record_count": 0,
        "held_record_count": 0,
        "file_contents": None,
    })
    return row


def new_record_dispute(body):
    row = entity()
    filed_at = clock.now()
    row.update({
        "employment_record_id": body.get("employment_record_id"),
        "covered_worker_id": body.get("covered_worker_id"),
        "claimed_field": body.get("claimed_field"),
        "claimed_correct_value": body.get("claimed_correct_value"),
        "filed_at": filed_at,
        "response_due_date": clock.add_days(filed_at, DISPUTE_RESPONSE_WINDOW_DAYS),
        "deadline_extended": False,
        "notice_sent_at": None,
        "resolved_at": None,
        "dispute_state": "FILED",
    })
    return row


def new_compensation_accrual(body):
    row = entity()
    row.update({
        "employer_id": body.get("employer_id"),
        "pay_period_end_date": clock.parse_iso(body.get("pay_period_end_date")),
        "transaction_ref": body.get("transaction_ref"),
        "records_count": body.get("records_count"),
        "unit_rate_cents": 0,
        "gross_accrued_cents": 0,
        "adjusted_cents": 0,
        "waived_cents": 0,
        "paid_cents": 0,
        "cycle_state": "ACCRUED",
    })
    return row


def new_data_currency_review(body):
    row = entity()
    row.update({
        "employer_id": body.get("employer_id"),
        "review_period_end": clock.parse_iso(body.get("review_period_end")),
        "window_days": body.get("window_days"),
        "last_feed_date_in_window": clock.parse_iso(body.get("last_feed_date_in_window")),
        "distinct_pay_periods_in_window": body.get("distinct_pay_periods_in_window"),
        "expected_periods": body.get("expected_periods"),
        "missing_periods": 0,
        "currency_score": 0,
        "review_state": "PENDING",
    })
    return row


def new_verification_attestation(body):
    row = entity()
    row.update({
        "verification_request_id": body.get("verification_request_id"),
        "verifier_id": body.get("verifier_id"),
        "attested_purpose": body.get("attested_purpose"),
        "signed_at": clock.now(),
        "attestation_state": "PENDING",
    })
    return row