"""Public wire representations of every entity (SCAFFOLD §1.1 fields).

System fields id/created_at/updated_at/version are appended to each resource
(PRD §2.5). Datetimes serialize as ISO 8601 UTC with three fractional digits.
Internal keys (underscore-prefixed) are never emitted.
"""
from db import STORE
from util import format_dt


def _sys(e):
    return {
        "created_at": format_dt(e["created_at"]),
        "updated_at": format_dt(e["updated_at"]),
        "version": e["version"],
    }


def serialize_creditor(c):
    # outstanding_receivable_cents is never stored; it is derived on every read
    # as the sum of current_balance_cents over ACTIVE / IN_COLLECTION debts
    # (SCAFFOLD calculations.outstanding_receivable_aggregation).
    outstanding = sum(
        d["current_balance_cents"]
        for d in STORE["debts"].values()
        if d["creditor_agency_id"] == c["id"] and d["status"] in ("ACTIVE", "IN_COLLECTION")
    )
    out = {
        "id": c["id"],
        "creditor_code": c["creditor_code"],
        "legal_name": c["legal_name"],
        "creditor_type": c["creditor_type"],
        "state_code": c["state_code"],
        "remitted_gross_ytd_cents": c["remitted_gross_ytd_cents"],
        "remitted_ytd_year": c["remitted_ytd_year"],
        "remitted_net_total_cents": c["remitted_net_total_cents"],
        "outstanding_receivable_cents": outstanding,
    }
    out.update(_sys(c))
    return out


def serialize_payee(p):
    out = {
        "id": p["id"],
        "tin": p["tin"],
        "tin_type": p["tin_type"],
        "legal_name": p["legal_name"],
        "routing_number": p["routing_number"],
        "account_last4": p["account_last4"],
    }
    out.update(_sys(p))
    return out


def serialize_policy(p):
    out = {
        "id": p["id"],
        "payment_type": p["payment_type"],
        "exemption_class": p["exemption_class"],
        "protected_minimum_cents": p["protected_minimum_cents"],
        "max_offset_pct": p["max_offset_pct"],
        "status": p["status"],
    }
    out.update(_sys(p))
    return out


def serialize_debt(d):
    out = {
        "id": d["id"],
        "creditor_agency_id": d["creditor_agency_id"],
        "debtor_tin": d["debtor_tin"],
        "debtor_name": d["debtor_name"],
        "debt_type": d["debt_type"],
        "original_amount_cents": d["original_amount_cents"],
        "current_balance_cents": d["current_balance_cents"],
        "priority_rank": d["priority_rank"],
        "delinquent_since": format_dt(d["delinquent_since"]),
        "notice_sent_at": format_dt(d["notice_sent_at"]),
        "due_process_completed": d["due_process_completed"],
        "returned_count": d["returned_count"],
        "status": d["status"],
    }
    out.update(_sys(d))
    return out


def serialize_file(f):
    out = {
        "id": f["id"],
        "agency_code": f["agency_code"],
        "settlement_date": format_dt(f["settlement_date"]),
        "status": f["status"],
        "payment_count": f["payment_count"],
        "total_offset_cents": f["total_offset_cents"],
        "total_disbursed_cents": f["total_disbursed_cents"],
    }
    out.update(_sys(f))
    return out


def serialize_payment(p):
    out = {
        "id": p["id"],
        "payment_file_id": p["payment_file_id"],
        "payee_id": p["payee_id"],
        "payee_tin": p["payee_tin"],
        "amount_cents": p["amount_cents"],
        "payment_type": p["payment_type"],
        "payment_method": p["payment_method"],
        "processing_status": p["processing_status"],
        "integrity_status": p["integrity_status"],
        "projected_offset_cents": p["projected_offset_cents"],
        "total_offset_cents": p["total_offset_cents"],
        "disbursed_cents": p["disbursed_cents"],
        "executed_by_user_id": p["executed_by_user_id"],
        "executed_at": format_dt(p["executed_at"]),
    }
    out.update(_sys(p))
    return out


def serialize_offset(o):
    out = {
        "id": o["id"],
        "payment_id": o["payment_id"],
        "debt_id": o["debt_id"],
        "priority_rank": o["priority_rank"],
        "offset_amount_cents": o["offset_amount_cents"],
        "fee_cents": o["fee_cents"],
        "net_remittance_cents": o["net_remittance_cents"],
        "applied_at": format_dt(o["applied_at"]),
        "status": o["status"],
    }
    out.update(_sys(o))
    return out


def serialize_claim(c):
    out = {
        "id": c["id"],
        "offset_id": c["offset_id"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "reason": c["reason"],
        "status": c["status"],
        "appeal_count": c["appeal_count"],
        "decided_by_user_id": c["decided_by_user_id"],
        "decided_at": format_dt(c["decided_at"]),
        "refund_amount_cents": c["refund_amount_cents"],
        "clawback_cents": c["clawback_cents"],
        "treasury_absorbed_cents": c["treasury_absorbed_cents"],
    }
    out.update(_sys(c))
    return out


def serialize_agency(a):
    out = {
        "id": a["id"],
        "agency_code": a["agency_code"],
        "name": a["name"],
        "capacity_max_active": a["capacity_max_active"],
    }
    out.update(_sys(a))
    return out


def serialize_action(a):
    out = {
        "id": a["id"],
        "debt_id": a["debt_id"],
        "collection_agency_id": a["collection_agency_id"],
        "action_type": a["action_type"],
        "notice_sent_at": format_dt(a["notice_sent_at"]),
        "disposable_pay_estimate_cents": a["disposable_pay_estimate_cents"],
        "projected_per_period_cents": a["projected_per_period_cents"],
        "collected_total_cents": a["collected_total_cents"],
        "status": a["status"],
    }
    out.update(_sys(a))
    return out


def serialize_reverse_request(r):
    out = {
        "id": r["id"],
        "state_code": r["state_code"],
        "payee_tin": r["payee_tin"],
        "requested_amount_cents": r["requested_amount_cents"],
        "status": r["status"],
        "matches": r["matches"],
        "matched_total_cents": r["matched_total_cents"],
        "expires_at": format_dt(r["expires_at"]),
        "confirmed_at": format_dt(r["confirmed_at"]),
        "applied_total_cents": r["applied_total_cents"],
    }
    out.update(_sys(r))
    return out


def serialize_agreement(a):
    out = {
        "id": a["id"],
        "state_code": a["state_code"],
        "direction": a["direction"],
        "effective_from": format_dt(a["effective_from"]),
        "effective_until": format_dt(a["effective_until"]),
        "status": a["status"],
    }
    out.update(_sys(a))
    return out


def serialize_dnp_record(r):
    out = {
        "id": r["id"],
        "tin": r["tin"],
        "list_source": r["list_source"],
        "effective_from": format_dt(r["effective_from"]),
        "effective_until": format_dt(r["effective_until"]),
        "status": r["status"],
    }
    out.update(_sys(r))
    return out
