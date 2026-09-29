"""Entity representations. Money is always an integer; instants carry 3 fractional digits."""
from util import fmt_iso


def _common(record, out):
    out["id"] = record["id"]
    out["created_at"] = fmt_iso(record["created_at"])
    out["updated_at"] = fmt_iso(record["updated_at"])
    out["version"] = int(record["version"])
    return out


def partner(record):
    out = {
        "id": record["id"],
        "legal_name": record["legal_name"],
        "parent_partner_id": record["parent_partner_id"],
        "business_model": record["business_model"],
        "funding_stage": record["funding_stage"],
        "months_runway": int(record["months_runway"]),
        "disclosed_complaints_per_10k": float(record["disclosed_complaints_per_10k"]),
        "end_user_account_count": int(record["end_user_account_count"]),
        "status": record["status"],
        "oversight_posture": record["oversight_posture"],
        "capability_tier": record["capability_tier"],
        "latest_composite_score": float(record["latest_composite_score"]),
        "complaint_rate_bps": int(record["complaint_rate_bps"]),
        "total_complaint_count": int(record["total_complaint_count"]),
        "open_complaint_count": int(record["open_complaint_count"]),
        "escalated_complaint_count": int(record["escalated_complaint_count"]),
        "resolved_complaint_count": int(record["resolved_complaint_count"]),
        "withdrawn_complaint_count": int(record["withdrawn_complaint_count"]),
        "open_sanctions_alert_count": int(record["open_sanctions_alert_count"]),
        "unreconciled_variance_cents": int(record["unreconciled_variance_cents"]),
        "required_reserve_cents": int(record["required_reserve_cents"]),
        "reserve_shortfall_cents": int(record["reserve_shortfall_cents"]),
        "consecutive_shortfall_cycles": int(record["consecutive_shortfall_cycles"]),
        "growth_breach_count": int(record["growth_breach_count"]),
        "concentration_ratio_pct": float(record["concentration_ratio_pct"]),
        "monthly_growth_pct": float(record["monthly_growth_pct"]),
        "cumulative_paid_out_cents": int(record["cumulative_paid_out_cents"]),
        "cumulative_bank_fee_cents": int(record["cumulative_bank_fee_cents"]),
        "created_by_user_id": record["created_by_user_id"],
    }
    return _common(record, out)


def diligence_review(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "review_type": record["review_type"],
        "business_model_score": int(record["business_model_score"]),
        "funding_score": int(record["funding_score"]),
        "compliance_capability_score": int(record["compliance_capability_score"]),
        "complaint_history_score": int(record["complaint_history_score"]),
        "effective_complaint_history_score": int(record["effective_complaint_history_score"]),
        "composite_score": float(record["composite_score"]),
        "tier": record["tier"],
        "status": record["status"],
        "revision_round": int(record["revision_round"]),
        "requested_info_items": list(record["requested_info_items"]),
        "submitted_by_user_id": record["submitted_by_user_id"],
        "decided_by_user_id": record["decided_by_user_id"],
    }
    return _common(record, out)


def agreement(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "kyc_owner": record["kyc_owner"],
        "dispute_owner": record["dispute_owner"],
        "marketing_owner": record["marketing_owner"],
        "oversight_rights_level": record["oversight_rights_level"],
        "audit_access_notice_days": int(record["audit_access_notice_days"]),
        "termination_triggers": list(record["termination_triggers"]),
        "monthly_growth_cap_pct": float(record["monthly_growth_cap_pct"]),
        "concentration_cap_pct": float(record["concentration_cap_pct"]),
        "max_end_user_balance_cents": int(record["max_end_user_balance_cents"]),
        "reserve_requirement_bps": int(record["reserve_requirement_bps"]),
        "effective_date": fmt_iso(record["effective_date"]),
        "status": record["status"],
        "revision_round": int(record["revision_round"]),
        "executed_at": fmt_iso(record["executed_at"]),
        "termination_trigger_fired": record["termination_trigger_fired"],
        "created_by_user_id": record["created_by_user_id"],
        "decided_by_user_id": record["decided_by_user_id"],
    }
    return _common(record, out)


def marketing_review(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "agreement_id": record["agreement_id"],
        "material_type": record["material_type"],
        "placement_channel": record["placement_channel"],
        "disclosure_elements": list(record["disclosure_elements"]),
        "apr_disclosed": bool(record["apr_disclosed"]),
        "fdic_signage_correct": bool(record["fdic_signage_correct"]),
        "effective_from": fmt_iso(record["effective_from"]),
        "effective_until": fmt_iso(record["effective_until"]),
        "status": record["status"],
        "review_round": int(record["review_round"]),
        "change_requests": list(record["change_requests"]),
        "risk_flags": list(record["risk_flags"]),
        "created_by_user_id": record["created_by_user_id"],
        "decided_by_user_id": record["decided_by_user_id"],
    }
    return _common(record, out)


def custody_account(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "account_type": record["account_type"],
        "balance_cents": int(record["balance_cents"]),
        "status": record["status"],
        "frozen_at": fmt_iso(record["frozen_at"]),
    }
    return _common(record, out)


def ledger_entry(record):
    # PRD 2.4: a ledger entry carries only id and created_at — no updated_at, no version.
    return {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "custody_account_id": record["custody_account_id"],
        "settlement_batch_id": record["settlement_batch_id"],
        "entry_type": record["entry_type"],
        "amount_cents": int(record["amount_cents"]),
        "effective_at": fmt_iso(record["effective_at"]),
        "sequence_no": int(record["sequence_no"]),
        "memo": record["memo"],
        "reversal_of_entry_id": record["reversal_of_entry_id"],
        "created_at": fmt_iso(record["created_at"]),
    }


def settlement_batch(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "window_start": fmt_iso(record["window_start"]),
        "window_end": fmt_iso(record["window_end"]),
        "gross_settlement_cents": int(record["gross_settlement_cents"]),
        "interchange_cents": int(record["interchange_cents"]),
        "returns_cents": int(record["returns_cents"]),
        "partner_reported_net_cents": int(record["partner_reported_net_cents"]),
        "bank_reported_net_cents": (None if record["bank_reported_net_cents"] is None
                                    else int(record["bank_reported_net_cents"])),
        "variance_cents": int(record["variance_cents"]),
        "variance_adjustment_cents": int(record["variance_adjustment_cents"]),
        "settlement_base_cents": int(record["settlement_base_cents"]),
        "bank_fee_bps_applied": int(record["bank_fee_bps_applied"]),
        "bank_fee_cents": int(record["bank_fee_cents"]),
        "reserve_funding_cents": int(record["reserve_funding_cents"]),
        "net_to_partner_cents": int(record["net_to_partner_cents"]),
        "shortfall_carry_cents": int(record["shortfall_carry_cents"]),
        "reconciliation_status": record["reconciliation_status"],
        "funding_status": record["funding_status"],
        "funded_at": fmt_iso(record["funded_at"]),
        "funding_reference": record["funding_reference"],
        "clawback_reason": record["clawback_reason"],
    }
    return _common(record, out)


def complaint(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "channel": record["channel"],
        "category": record["category"],
        "severity": record["severity"],
        "received_at": fmt_iso(record["received_at"]),
        "narrative": record["narrative"],
        "is_reg_e_dispute": bool(record["is_reg_e_dispute"]),
        "handling_owner": record["handling_owner"],
        "response_due_at": fmt_iso(record["response_due_at"]),
        "status": record["status"],
        "root_cause_code": record["root_cause_code"],
        "escalation_count": int(record["escalation_count"]),
        "redress_cents": int(record["redress_cents"]),
        "resolved_at": fmt_iso(record["resolved_at"]),
    }
    return _common(record, out)


def alert(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "alert_type": record["alert_type"],
        "triggered_at": fmt_iso(record["triggered_at"]),
        "transaction_volume_cents": int(record["transaction_volume_cents"]),
        "detection_note": record["detection_note"],
        "sla_due_at": fmt_iso(record["sla_due_at"]),
        "disposition": record["disposition"],
        "sla_breach_count": int(record["sla_breach_count"]),
        "disposed_by_user_id": record["disposed_by_user_id"],
    }
    return _common(record, out)


def cycle(record):
    out = {
        "id": record["id"],
        "cycle_index": int(record["cycle_index"]),
        "cycle_label": record["cycle_label"],
        "period_start": fmt_iso(record["period_start"]),
        "period_end": fmt_iso(record["period_end"]),
        "status": record["status"],
        "closed_at": fmt_iso(record["closed_at"]),
        "partners_frozen_count": int(record["partners_frozen_count"]),
        "marketing_approvals_expired_count": int(record["marketing_approvals_expired_count"]),
        "complaints_escalated_count": int(record["complaints_escalated_count"]),
        "alerts_reopened_count": int(record["alerts_reopened_count"]),
        "growth_breach_partner_count": int(record["growth_breach_partner_count"]),
        "plans_completed_count": int(record["plans_completed_count"]),
    }
    return _common(record, out)


def wind_down_plan(record):
    out = {
        "id": record["id"],
        "partner_id": record["partner_id"],
        "trigger_reason": record["trigger_reason"],
        "end_user_funds_disposition": record["end_user_funds_disposition"],
        "notice_days": int(record["notice_days"]),
        "target_completion_date": fmt_iso(record["target_completion_date"]),
        "milestones": list(record["milestones"]),
        "status": record["status"],
        "revision_round": int(record["revision_round"]),
        "residual_balance_cents": int(record["residual_balance_cents"]),
        "approved_by_user_id": record["approved_by_user_id"],
        "completed_at": fmt_iso(record["completed_at"]),
        "created_by_user_id": record["created_by_user_id"],
    }
    return _common(record, out)
