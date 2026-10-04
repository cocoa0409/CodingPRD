"""Entity serializers. Computed fields (attestation status, authorization
in_effect, batch open_exception_count, transaction remaining_refundable_cents)
re-derive from the logical clock on every read; nothing is snapshotted.
Input-sourced instants echo the caller's original string."""
import clock
import helpers


def _echo(rec, field):
    raw = rec.get(field + "_raw")
    if raw is not None:
        return raw
    return clock.fmt(rec.get(field))


def agency(a):
    return {
        "id": a["id"],
        "legal_name": a["legal_name"],
        "agency_type": a["agency_type"],
        "default_fee_model": a["default_fee_model"],
        "status": a["status"],
        "activated_at": clock.fmt(a["activated_at"]),
        "created_at": clock.fmt(a["created_at"]),
        "updated_at": clock.fmt(a["updated_at"]),
        "version": a["version"],
    }


def account(acc):
    return {
        "id": acc["id"],
        "agency_id": acc["agency_id"],
        "routing_number": acc["routing_number"],
        "account_number_last4": acc["account_number_last4"],
        "effective_from": _echo(acc, "effective_from"),
        "effective_to": _echo(acc, "effective_to"),
        "status": acc["status"],
        "verification_attempts": acc["verification_attempts"],
        "verified_at": clock.fmt(acc["verified_at"]),
        "created_at": clock.fmt(acc["created_at"]),
        "updated_at": clock.fmt(acc["updated_at"]),
        "version": acc["version"],
    }


def tier(t):
    return {
        "id": t["id"],
        "agency_id": t["agency_id"],
        "volume_min_cents": t["volume_min_cents"],
        "volume_max_cents": t["volume_max_cents"],
        "rate_bp": t["rate_bp"],
        "per_txn_cents": t["per_txn_cents"],
        "effective_month": t["effective_month"],
        "created_at": clock.fmt(t["created_at"]),
    }


def attestation(att):
    return {
        "id": att["id"],
        "agency_id": att["agency_id"],
        "attestation_type": att["attestation_type"],
        "issued_at": _echo(att, "issued_at"),
        "expires_at": _echo(att, "expires_at"),
        "status": helpers.attestation_status(att),
        "created_at": clock.fmt(att["created_at"]),
    }


def service(s):
    return {
        "id": s["id"],
        "agency_id": s["agency_id"],
        "service_code": s["service_code"],
        "name": s["name"],
        "fee_model": s["fee_model"],
        "allowed_methods": list(s["allowed_methods"]),
        "min_amount_cents": s["min_amount_cents"],
        "max_amount_cents": s["max_amount_cents"],
        "gl_code": s["gl_code"],
        "status": s["status"],
        "created_at": clock.fmt(s["created_at"]),
        "updated_at": clock.fmt(s["updated_at"]),
        "version": s["version"],
    }


def authorization(auth):
    return {
        "id": auth["id"],
        "service_id": auth["service_id"],
        "statute_citation": auth["statute_citation"],
        "disclosure_text_version": auth["disclosure_text_version"],
        "fee_cap_cents": auth["fee_cap_cents"],
        "effective_from": _echo(auth, "effective_from"),
        "effective_to": _echo(auth, "effective_to"),
        "status": auth["status"],
        "in_effect": helpers.authorization_in_effect(auth),
        "created_at": clock.fmt(auth["created_at"]),
        "updated_at": clock.fmt(auth["updated_at"]),
        "version": auth["version"],
    }


def payer(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "billing_zip": p["billing_zip"],
        "created_at": clock.fmt(p["created_at"]),
        "updated_at": clock.fmt(p["updated_at"]),
        "version": p["version"],
    }


def instrument(i):
    return {
        "id": i["id"],
        "payer_id": i["payer_id"],
        "method": i["method"],
        "card_brand": i["card_brand"],
        "card_cost_bucket": i["card_cost_bucket"],
        "last4": i["last4"],
        "token_ref": i["token_ref"],
        "status": i["status"],
        "ach_verify_failures": i["ach_verify_failures"],
        "created_at": clock.fmt(i["created_at"]),
        "updated_at": clock.fmt(i["updated_at"]),
        "version": i["version"],
    }


def quote(q):
    return {
        "id": q["id"],
        "service_id": q["service_id"],
        "payer_id": q["payer_id"],
        "statutory_authorization_id": q["statutory_authorization_id"],
        "amount_cents": q["amount_cents"],
        "method": q["method"],
        "quoted_fee_cents": q["quoted_fee_cents"],
        "payer_total_cents": q["payer_total_cents"],
        "disclosure_text_version": q["disclosure_text_version"],
        "service_version_pinned": q["service_version_pinned"],
        "expires_at": clock.fmt(q["expires_at"]),
        "status": q["status"],
        "created_at": clock.fmt(q["created_at"]),
    }


def transaction(t):
    return {
        "id": t["id"],
        "quote_id": t["quote_id"],
        "instrument_id": t["instrument_id"],
        "service_id": t["service_id"],
        "agency_id": t["agency_id"],
        "payer_id": t["payer_id"],
        "current_batch_id": t["current_batch_id"],
        "method": t["method"],
        "fee_model": t["fee_model"],
        "amount_cents": t["amount_cents"],
        "charged_fee_cents": t["charged_fee_cents"],
        "final_fee_cents": t["final_fee_cents"],
        "payer_total_cents": t["payer_total_cents"],
        "funds_status": t["funds_status"],
        "representment_count": t["representment_count"],
        "captured_at": clock.fmt(t["captured_at"]),
        "value_date": t["value_date"],
        "returned_at": clock.fmt(t["returned_at"]),
        "refunded_cents": t["refunded_cents"],
        "charged_back_cents": t["charged_back_cents"],
        "remaining_refundable_cents": helpers.remaining_refundable(t),
        "created_at": clock.fmt(t["created_at"]),
        "updated_at": clock.fmt(t["updated_at"]),
        "version": t["version"],
    }


def batch(b):
    return {
        "id": b["id"],
        "agency_id": b["agency_id"],
        "business_date": b["business_date"],
        "status": b["status"],
        "member_count": b["member_count"],
        "gross_amount_cents": b["gross_amount_cents"],
        "fees_withheld_cents": b["fees_withheld_cents"],
        "refund_debits_cents": b["refund_debits_cents"],
        "return_debits_cents": b["return_debits_cents"],
        "chargeback_debits_cents": b["chargeback_debits_cents"],
        "deposit_cents": b["deposit_cents"],
        "deposit_due_date": b["deposit_due_date"],
        "submitted_at": clock.fmt(b["submitted_at"]),
        "confirmed_at": clock.fmt(b["confirmed_at"]),
        "actual_deposit_cents": b["actual_deposit_cents"],
        "open_exception_count": helpers.open_exception_count(b["id"]),
        "created_at": clock.fmt(b["created_at"]),
        "updated_at": clock.fmt(b["updated_at"]),
        "version": b["version"],
    }


def exception(e):
    return {
        "id": e["id"],
        "batch_id": e["batch_id"],
        "exception_type": e["exception_type"],
        "expected_cents": e["expected_cents"],
        "actual_cents": e["actual_cents"],
        "detail": e["detail"],
        "status": e["status"],
        "resolution_note": e["resolution_note"],
        "created_at": clock.fmt(e["created_at"]),
        "updated_at": clock.fmt(e["updated_at"]),
        "version": e["version"],
    }


def refund(r):
    return {
        "id": r["id"],
        "transaction_id": r["transaction_id"],
        "amount_cents": r["amount_cents"],
        "reason": r["reason"],
        "initiated_by_user_id": r["initiated_by_user_id"],
        "decided_by_user_id": r["decided_by_user_id"],
        "status": r["status"],
        "created_at": clock.fmt(r["created_at"]),
        "updated_at": clock.fmt(r["updated_at"]),
        "version": r["version"],
    }


def chargeback(c):
    return {
        "id": c["id"],
        "transaction_id": c["transaction_id"],
        "reason_code": c["reason_code"],
        "network_debit_cents": c["network_debit_cents"],
        "opened_at": clock.fmt(c["opened_at"]),
        "evidence_due_at": clock.fmt(c["evidence_due_at"]),
        "evidence_note": c["evidence_note"],
        "status": c["status"],
        "created_at": clock.fmt(c["created_at"]),
        "updated_at": clock.fmt(c["updated_at"]),
        "version": c["version"],
    }


def ledger_entry(e):
    return {
        "id": e["id"],
        "period": e["period"],
        "fees_collected_cents": e["fees_collected_cents"],
        "absorbed_billed_cents": e["absorbed_billed_cents"],
        "absorbed_billed_flat_cents": e["absorbed_billed_flat_cents"],
        "processing_costs_cents": e["processing_costs_cents"],
        "accrual_portal_recovery_cents": e["accrual_portal_recovery_cents"],
        "cash_portal_recovery_cents": e["cash_portal_recovery_cents"],
        "surplus_remitted_cents": e["surplus_remitted_cents"],
        "pool_balance_after_cents": e["pool_balance_after_cents"],
        "portal_cost_remaining_accrual_cents": e["portal_cost_remaining_accrual_cents"],
        "portal_cost_remaining_cash_cents": e["portal_cost_remaining_cash_cents"],
        "created_at": clock.fmt(e["created_at"]),
    }
