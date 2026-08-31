"""Entity serializers. Every row exposes id, created_at, updated_at, version."""
from core import iso
import calc


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = iso(row["created_at"])
    out["updated_at"] = iso(row["updated_at"])
    out["version"] = row["version"]
    return out


def customer(row):
    return _common(
        row,
        {
            "legal_name": row["legal_name"],
            "tin_last4": row["tin_last4"],
            "kyc_tier": row["kyc_tier"],
            "watchlist_hit": row["watchlist_hit"],
            "preservation_hold_active": calc.preservation_hold_active(row["id"]),
            "open_fraud_case_count": calc.open_fraud_case_count(row["id"]),
        },
    )


def account(row):
    return _common(
        row,
        {
            "customer_id": row["customer_id"],
            "product_type": row["product_type"],
            "open_channel": row["open_channel"],
            "opened_at": iso(row["opened_at"]),
            "lifecycle_status": row["lifecycle_status"],
            "access_posture": row["access_posture"],
            "risk_score": row["risk_score"],
            "risk_score_basis": row["risk_score_basis"],
            "risk_band": row["risk_band"],
            "ato_indicator_codes": list(row["ato_indicator_codes"]),
            "ato_score": row["ato_score"],
            "step_up_failure_count": row["step_up_failure_count"],
            "ledger_balance_cents": row["ledger_balance_cents"],
            "available_balance_cents": row["available_balance_cents"],
            "held_amount_cents": calc.held_amount_cents(row["id"]),
            "charged_off_amount_cents": row["charged_off_amount_cents"],
            "closure_scheduled_at": iso(row["closure_scheduled_at"]),
            "closure_reason": row["closure_reason"],
        },
    )


def funding_source(row):
    return _common(
        row,
        {
            "account_id": row["account_id"],
            "source_type": row["source_type"],
            "routing_last4": row["routing_last4"],
            "micro_deposit_cents": row["micro_deposit_cents"],
            "verification_status": row["verification_status"],
            "attempt_count": row["attempt_count"],
            "total_attempt_count": row["total_attempt_count"],
            "verified_at": iso(row["verified_at"]),
        },
    )


def account_link(row):
    return _common(
        row,
        {
            "from_account_id": row["from_account_id"],
            "to_account_id": row["to_account_id"],
            "link_type": row["link_type"],
            "confidence_bps": row["confidence_bps"],
            "is_risk_bearing": row["is_risk_bearing"],
        },
    )


def deposit_item(row):
    return _common(
        row,
        {
            "account_id": row["account_id"],
            "drawee_account_id": row["drawee_account_id"],
            "item_type": row["item_type"],
            "amount_cents": row["amount_cents"],
            "deposit_at": iso(row["deposit_at"]),
            "status": row["status"],
            "settled_at": iso(row["settled_at"]),
            "return_reason": row["return_reason"],
            "immediate_credit_cents": row["immediate_credit_cents"],
            "held_cents": row["held_cents"],
        },
    )


def check_hold(row):
    return _common(
        row,
        {
            "deposit_item_id": row["deposit_item_id"],
            "hold_type": row["hold_type"],
            "held_amount_cents": row["held_amount_cents"],
            "hold_start_at": iso(row["hold_start_at"]),
            "hold_release_at": iso(row["hold_release_at"]),
            "status": row["status"],
            "released_at": iso(row["released_at"]),
        },
    )


def override_review(row):
    return _common(
        row,
        {
            "check_hold_id": row["check_hold_id"],
            "requested_release_cents": row["requested_release_cents"],
            "release_effective_at": iso(row["release_effective_at"]),
            "release_window_end_at": iso(row["release_window_end_at"]),
            "justification": row["justification"],
            "prepared_by_user_id": row["prepared_by_user_id"],
            "decided_by_user_id": row["decided_by_user_id"],
            "status": row["status"],
            "loss_exposure_cents": row["loss_exposure_cents"],
            "adjusted_exposure_cents": row["adjusted_exposure_cents"],
            "decision_note": row["decision_note"],
            "revision_count": row["revision_count"],
            "submitted_at": iso(row["submitted_at"]),
            "decided_at": iso(row["decided_at"]),
            "executed_at": iso(row["executed_at"]),
        },
    )


def fraud_case(row):
    return _common(
        row,
        {
            "primary_account_id": row["primary_account_id"],
            "case_type": row["case_type"],
            "status": row["status"],
            "detection_source": row["detection_source"],
            "kiting_score": row["kiting_score"],
            "scan_mode": row["scan_mode"],
            "cycle_account_ids": list(row["cycle_account_ids"]),
            "exposure_at_risk_cents": row["exposure_at_risk_cents"],
            "disposition_note": row["disposition_note"],
            "reopen_count": row["reopen_count"],
            "closed_at": iso(row["closed_at"]),
        },
    )


def charge_off(row):
    return _common(
        row,
        {
            "account_id": row["account_id"],
            "gross_loss_cents": row["gross_loss_cents"],
            "collateral_offset_cents": row["collateral_offset_cents"],
            "base_net_cents": row["base_net_cents"],
            "recovery_fee_cents": row["recovery_fee_cents"],
            "net_charge_off_cents": row["net_charge_off_cents"],
            "principal_recovered_cents": row["principal_recovered_cents"],
            "fee_recovered_cents": row["fee_recovered_cents"],
            "outstanding_loss_cents": calc.outstanding_loss(row),
            "status": row["status"],
            "approved_by_user_id": row["approved_by_user_id"],
            "booked_by_user_id": row["booked_by_user_id"],
            "ledger_balance_before_book_cents": row["ledger_balance_before_book_cents"],
            "booked_at": iso(row["booked_at"]),
            "reversed_at": iso(row["reversed_at"]),
        },
    )


def subpoena(row):
    return _common(
        row,
        {
            "customer_id": row["customer_id"],
            "issuing_agency": row["issuing_agency"],
            "docket_number": row["docket_number"],
            "received_at": iso(row["received_at"]),
            "response_due_at": iso(row["response_due_at"]),
            "preservation_start_at": iso(row["preservation_start_at"]),
            "preservation_end_at": iso(row["preservation_end_at"]),
            "status": row["status"],
            "legal_reviewed_by_user_id": row["legal_reviewed_by_user_id"],
            "responded_by_user_id": row["responded_by_user_id"],
            "is_late": row["is_late"],
            "production_note": row["production_note"],
        },
    )


def bsa_referral(row):
    return _common(
        row,
        {
            "fraud_case_id": row["fraud_case_id"],
            "narrative": row["narrative"],
            "suspected_activity_code": row["suspected_activity_code"],
            "aggregate_amount_cents": row["aggregate_amount_cents"],
            "status": row["status"],
            "drafted_by_user_id": row["drafted_by_user_id"],
            "adjudicated_by_user_id": row["adjudicated_by_user_id"],
            "return_reason": row["return_reason"],
            "revision_count": row["revision_count"],
            "submitted_at": iso(row["submitted_at"]),
            "adjudicated_at": iso(row["adjudicated_at"]),
        },
    )
