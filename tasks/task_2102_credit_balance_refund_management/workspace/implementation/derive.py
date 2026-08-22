"""Derived balances (PRD 2.9) and JSON serialisation of every entity."""
import clock
import db

OPEN_CREDIT_STATUSES = ("IDENTIFIED", "UNDER_REVIEW", "ATTRIBUTED", "REFUND_PENDING")
REFUNDED_CHECK_STATES = ("ISSUED", "CLEARED", "STALE", "REISSUED", "ESCHEATED")
SWEEP_BLOCKING_STATUSES = ("IDENTIFIED", "UNDER_REVIEW", "ATTRIBUTED", "REFUND_PENDING", "REFUNDED")

MEDICARE_REPAYMENT_WINDOW_DAYS = 60
LATE_TIER_1_NUM, LATE_TIER_1_DEN = 2, 100
LATE_TIER_2_NUM, LATE_TIER_2_DEN = 5, 100
LATE_TIER_3_NUM, LATE_TIER_3_DEN = 10, 100


# ------------------------------------------------------------------ account
def account_balance_cents(account_id):
    """Sum of amount_cents over ALL transactions, reversal rows included."""
    return sum(int(t["amount_cents"]) for t in db.account_transactions.values()
               if t["account_id"] == account_id)


def account_credit_balance_cents(account_id):
    return sum(int(c["credit_amount_cents"]) for c in db.credit_balances.values()
               if c["account_id"] == account_id and c["status"] in OPEN_CREDIT_STATUSES)


def account_last_activity_at(account_id):
    stamps = [t["posted_at"] for t in db.account_transactions.values()
              if t["account_id"] == account_id and not txn_is_reversed(t)]
    return max(stamps) if stamps else None


def txn_is_reversed(txn):
    return txn["id"] in db.reversed_transaction_ids


# ------------------------------------------------------------ credit balance
def cb_refunded_cents(cb):
    total = 0
    for chk in db.checks_for_credit_balance(cb["id"]):
        if chk["state"] in REFUNDED_CHECK_STATES:
            total += int(chk["gross_amount_cents"])
    return total


def cb_offset_cents(cb):
    return sum(int(o["applied_cents"]) for o in db.offsets_for_credit_balance(cb["id"])
               if o["state"] == "APPLIED")


def cb_outstanding_cents(cb):
    return int(cb["credit_amount_cents"]) - cb_refunded_cents(cb) - cb_offset_cents(cb)


def cb_aging_days(cb, as_of=None):
    return clock.whole_days(as_of or clock.now(), cb["identified_at"])


def aging_bucket(days):
    if days <= 30:
        return "D0_30"
    if days <= 60:
        return "D31_60"
    if days <= 90:
        return "D61_90"
    if days <= 180:
        return "D91_180"
    return "OVER_180"


def cb_root_cause_confirmed(cb):
    return any(bool(f["confirmed"]) for f in db.findings_for_credit_balance(cb["id"]))


# ------------------------------------------------------------ refund request
def rr_approvals_received(rr):
    return len([a for a in db.approvals_for_request(rr["id"]) if a["decision"] == "APPROVED"])


def rr_approved_amount_cents(rr):
    return int(rr["requested_amount_cents"]) if rr["approval_state"] == "APPROVED" else 0


# -------------------------------------------------------------- refund batch
def batch_counted_checks(batch_id):
    return [c for c in db.checks_for_batch(batch_id) if c["state"] != "VOIDED"]


def batch_totals(batch_id):
    counted = batch_counted_checks(batch_id)
    return {
        "item_count": len(counted),
        "total_gross_cents": sum(int(c["gross_amount_cents"]) for c in counted),
        "total_fee_cents": sum(int(c["processing_fee_cents"]) for c in counted),
        "total_net_cents": sum(int(c["net_check_amount_cents"]) for c in counted),
    }


# ------------------------------------------------------------------- notice
def notice_applied_cents(notice):
    return sum(int(o["applied_cents"]) for o in db.offsets_for_notice(notice["id"])
               if o["state"] == "APPLIED")


def notice_remaining_cents(notice):
    return int(notice["total_recoup_cents"]) - notice_applied_cents(notice)


# --------------------------------------------------------------- obligation
def obligation_days_elapsed(ob, as_of=None):
    return clock.whole_days(as_of or clock.now(), ob["identified_at"])


def obligation_days_late(ob, as_of=None):
    return max(0, obligation_days_elapsed(ob, as_of) - MEDICARE_REPAYMENT_WINDOW_DAYS)


def penalty_for_days_late(reportable_cents, days_late):
    if days_late == 0:
        return 0
    if days_late <= 30:
        return clock.round_half_up(reportable_cents * LATE_TIER_1_NUM, LATE_TIER_1_DEN)
    if days_late <= 90:
        return clock.round_half_up(reportable_cents * LATE_TIER_2_NUM, LATE_TIER_2_DEN)
    return clock.round_half_up(reportable_cents * LATE_TIER_3_NUM, LATE_TIER_3_DEN)


LIVE_OBLIGATION_STATES = ("OPEN", "LATE")


def obligation_penalty_cents(ob):
    """Recomputed against the logical clock while the obligation is still live;
    frozen at the value written on report / satisfaction otherwise."""
    if ob["state"] in LIVE_OBLIGATION_STATES:
        return penalty_for_days_late(int(ob["reportable_amount_cents"]), obligation_days_late(ob))
    return int(ob.get("penalty_cents") or 0)


def refresh_obligation(ob):
    """Write the derived day counts / penalty onto the row (sweep, report,
    reopening)."""
    ob["days_elapsed"] = obligation_days_elapsed(ob)
    ob["days_late"] = obligation_days_late(ob)
    ob["penalty_cents"] = penalty_for_days_late(int(ob["reportable_amount_cents"]),
                                                ob["days_late"])
    return ob


# --------------------------------------------------------------- serialisers
def _dt(value):
    return clock.iso(value)


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = _dt(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = _dt(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def payer(row):
    return _common(row, {
        "name": row["name"],
        "payer_code": row["payer_code"],
        "payer_type": row["payer_type"],
        "take_back_allowed": row["take_back_allowed"],
        "refund_remit_days": row["refund_remit_days"],
    })


def patient_account(row):
    return _common(row, {
        "account_number": row["account_number"],
        "mrn": row["mrn"],
        "patient_name": row["patient_name"],
        "guarantor_state_code": row["guarantor_state_code"],
        "primary_payer_id": row["primary_payer_id"],
        "financial_class": row["financial_class"],
        "discharge_date": _dt(row["discharge_date"]),
        "balance_cents": account_balance_cents(row["id"]),
        "credit_balance_cents": account_credit_balance_cents(row["id"]),
        "last_activity_at": _dt(account_last_activity_at(row["id"])),
        "status": row["status"],
    })


def account_transaction(row):
    return _common(row, {
        "account_id": row["account_id"],
        "txn_type": row["txn_type"],
        "amount_cents": int(row["amount_cents"]),
        "source": row["source"],
        "payer_id": row["payer_id"],
        "posted_at": _dt(row["posted_at"]),
        "effective_at": _dt(row["effective_at"]),
        "reversal_of_transaction_id": row["reversal_of_transaction_id"],
        "is_reversed": txn_is_reversed(row),
        "remark": row["remark"],
    })


def credit_balance(row):
    days = cb_aging_days(row)
    return _common(row, {
        "account_id": row["account_id"],
        "payer_id": row["payer_id"],
        "credit_amount_cents": int(row["credit_amount_cents"]),
        "identified_at": _dt(row["identified_at"]),
        "attribution_method": row["attribution_method"],
        "attribution": row["attribution"],
        "patient_portion_cents": int(row["patient_portion_cents"]),
        "payer_portion_cents": int(row["payer_portion_cents"]),
        "refunded_cents": cb_refunded_cents(row),
        "offset_cents": cb_offset_cents(row),
        "outstanding_cents": cb_outstanding_cents(row),
        "aging_days": days,
        "aging_bucket": aging_bucket(days),
        "root_cause_confirmed": cb_root_cause_confirmed(row),
        "status": row["status"],
    })


def root_cause_finding(row):
    return _common(row, {
        "credit_balance_id": row["credit_balance_id"],
        "cause_code": row["cause_code"],
        "corrective_action": row["corrective_action"],
        "evidence_transaction_ids": list(row["evidence_transaction_ids"]),
        "narrative": row["narrative"],
        "analyst_user_id": row["analyst_user_id"],
        "confirmed": bool(row["confirmed"]),
    })


def refund_request(row):
    return _common(row, {
        "credit_balance_id": row["credit_balance_id"],
        "requested_amount_cents": int(row["requested_amount_cents"]),
        "approved_amount_cents": rr_approved_amount_cents(row),
        "payee_type": row["payee_type"],
        "payee_name": row["payee_name"],
        "payee_address_line": row["payee_address_line"],
        "payee_state_code": row["payee_state_code"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "required_approval_tier": row["required_approval_tier"],
        "required_approval_count": row["required_approval_count"],
        "approvals_received": rr_approvals_received(row),
        "revision_count": row["revision_count"],
        "last_decision_user_id": row["last_decision_user_id"],
        "approval_state": row["approval_state"],
        "disbursement_state": row["disbursement_state"],
    })


def refund_approval(row):
    return _common(row, {
        "refund_request_id": row["refund_request_id"],
        "approver_user_id": row["approver_user_id"],
        "approver_tier": row["approver_tier"],
        "decision": row["decision"],
        "note": row["note"],
        "decided_at": _dt(row["decided_at"]),
    })


def refund_batch(row):
    totals = batch_totals(row["id"])
    out = {
        "batch_number": row["batch_number"],
        "bank_account_code": row["bank_account_code"],
        "cutoff_at": _dt(row["cutoff_at"]),
        "scheduled_run_at": _dt(row["scheduled_run_at"]),
        "state": row["state"],
    }
    out.update(totals)
    return _common(row, out)


def check_disbursement(row):
    return _common(row, {
        "refund_request_id": row["refund_request_id"],
        "refund_batch_id": row["refund_batch_id"],
        "reissue_of_disbursement_id": row["reissue_of_disbursement_id"],
        "check_number": row["check_number"],
        "gross_amount_cents": int(row["gross_amount_cents"]),
        "processing_fee_cents": int(row["processing_fee_cents"]),
        "net_check_amount_cents": int(row["net_check_amount_cents"]),
        "payee_state_code": row["payee_state_code"],
        "issued_at": _dt(row["issued_at"]),
        "cleared_at": _dt(row["cleared_at"]),
        "stale_at": _dt(row["stale_at"]),
        "void_reason": row["void_reason"],
        "state": row["state"],
    })


def take_back_notice(row):
    return _common(row, {
        "payer_id": row["payer_id"],
        "notice_number": row["notice_number"],
        "total_recoup_cents": int(row["total_recoup_cents"]),
        "admin_fee_cents": int(row["admin_fee_cents"]),
        "received_at": _dt(row["received_at"]),
        "dispute_deadline_at": _dt(row["dispute_deadline_at"]),
        "applied_cents": notice_applied_cents(row),
        "remaining_unapplied_cents": notice_remaining_cents(row),
        "state": row["state"],
    })


def offset_application(row):
    return _common(row, {
        "take_back_notice_id": row["take_back_notice_id"],
        "account_id": row["account_id"],
        "credit_balance_id": row["credit_balance_id"],
        "posted_transaction_id": row["posted_transaction_id"],
        "applied_cents": int(row["applied_cents"]),
        "admin_fee_share_cents": int(row["admin_fee_share_cents"]),
        "sequence": row["sequence"],
        "applied_at": _dt(row["applied_at"]),
        "reversed_at": _dt(row["reversed_at"]),
        "state": row["state"],
    })


def medicare_obligation(row):
    return _common(row, {
        "credit_balance_id": row["credit_balance_id"],
        "payer_id": row["payer_id"],
        "identified_at": _dt(row["identified_at"]),
        "due_at": _dt(row["due_at"]),
        "reportable_amount_cents": int(row["reportable_amount_cents"]),
        "days_elapsed": obligation_days_elapsed(row),
        "days_late": obligation_days_late(row),
        "penalty_cents": obligation_penalty_cents(row),
        "report_reference": row["report_reference"],
        "reported_at": _dt(row["reported_at"]),
        "satisfied_at": _dt(row["satisfied_at"]),
        "satisfaction_mode": row["satisfaction_mode"],
        "state": row["state"],
    })


def escheatment_record(row):
    return _common(row, {
        "check_disbursement_id": row["check_disbursement_id"],
        "basis": row["basis"],
        "state_code": row["state_code"],
        "dormancy_days": row["dormancy_days"],
        "dormancy_start_at": _dt(row["dormancy_start_at"]),
        "escheat_due_at": _dt(row["escheat_due_at"]),
        "due_diligence_open_at": _dt(row["due_diligence_open_at"]),
        "contact_method": row["contact_method"],
        "due_diligence_sent_at": _dt(row["due_diligence_sent_at"]),
        "remitted_amount_cents": int(row["remitted_amount_cents"]),
        "claimed_at": _dt(row["claimed_at"]),
        "state": row["state"],
    })


def compliance_report(row):
    return _common(row, {
        "report_type": row["report_type"],
        "scope_code": row["scope_code"],
        "period_start_at": _dt(row["period_start_at"]),
        "period_end_at": _dt(row["period_end_at"]),
        "as_of_at": _dt(row["as_of_at"]),
        "total_liability_cents": int(row["total_liability_cents"]),
        "patient_liability_cents": int(row["patient_liability_cents"]),
        "payer_liability_cents": int(row["payer_liability_cents"]),
        "medicare_at_risk_cents": int(row["medicare_at_risk_cents"]),
        "over_180_count": int(row["over_180_count"]),
        "line_count": int(row["line_count"]),
        "generated_by_user_id": row["generated_by_user_id"],
        "state": row["state"],
    })
