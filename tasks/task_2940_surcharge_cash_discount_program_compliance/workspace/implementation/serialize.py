"""Entity representations returned in the envelope's `data` field."""

import calc
from store import fmt_ts


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def jurisdiction(row):
    out = {
        "id": row["id"],
        "state_code": row["state_code"],
        "surcharge_permitted": row["surcharge_permitted"],
        "surcharge_cap_pct": row["surcharge_cap_pct"],
        "cash_discount_permitted": row["cash_discount_permitted"],
        "price_posting_required": row["price_posting_required"],
        "disclosure_signage_required": row["disclosure_signage_required"],
        "receipt_line_item_required": row["receipt_line_item_required"],
        "ag_enforcement_posture": row["ag_enforcement_posture"],
        "law_change_count": row["law_change_count"],
        "last_law_change_at": fmt_ts(row["last_law_change_at"]),
    }
    out.update(_common(row))
    return out


def merchant(row):
    gross = calc.gross_surcharge_collected(row["id"])
    issued = calc.issued_refund_total_for_merchant(row["id"])
    out = {
        "id": row["id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "legal_name": row["legal_name"],
        "mcc": row["mcc"],
        "gross_surcharge_collected_cents": gross,
        "net_surcharge_collected_cents": gross - issued,
        "enforcing_terminal_count": calc.enforcing_terminal_count(row["id"]),
        "active_cost_documentation_id": calc.active_cost_documentation_id(row["id"]),
    }
    out.update(_common(row))
    return out


def cost_documentation(row):
    out = {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "base_mdr_pct": row["base_mdr_pct"],
        "assessment_pct": row["assessment_pct"],
        "per_item_fee_cents": row["per_item_fee_cents"],
        "evidence_uri": row["evidence_uri"],
        "average_ticket_cents": row["average_ticket_cents"],
        "documented_cost_pct": row["documented_cost_pct"],
        "attested_by_user_id": row["attested_by_user_id"],
        "effective_from": fmt_ts(row["effective_from"]),
        "state": row["state"],
        "superseded_at": fmt_ts(row["superseded_at"]),
    }
    out.update(_common(row))
    return out


def program(row):
    out = {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "cost_documentation_id": row["cost_documentation_id"],
        "program_type": row["program_type"],
        "consistency_scope": row["consistency_scope"],
        "status": row["status"],
        "disable_reason": row["disable_reason"],
        "effective_cap_pct": row["effective_cap_pct"],
        "disclosure_ready": row["disclosure_ready"],
        "network_exposure_score": row["network_exposure_score"],
        "ag_exposure_score": row["ag_exposure_score"],
        "activated_at": fmt_ts(row["activated_at"]),
        "activated_by_user_id": row["activated_by_user_id"],
        "cost_documentation_pinned_at": fmt_ts(row["cost_documentation_pinned_at"]),
    }
    out.update(_common(row))
    return out


def rate_rule(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "brand": row["brand"],
        "product_tier": row["product_tier"],
        "rate_pct": row["rate_pct"],
        "effective_from": fmt_ts(row["effective_from"]),
        "effective_to": fmt_ts(row["effective_to"]),
        "created_by_user_id": row["created_by_user_id"],
    }
    out.update(_common(row))
    return out


def registration(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "network": row["network"],
        "registration_ref": row["registration_ref"],
        "submitted_at": fmt_ts(row["submitted_at"]),
        "notice_days": row["notice_days"],
        "earliest_effective_at": fmt_ts(row["earliest_effective_at"]),
        "state": row["state"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_note": row["decision_note"],
        "effective_at": fmt_ts(row["effective_at"]),
        "revoked_at": fmt_ts(row["revoked_at"]),
    }
    out.update(_common(row))
    return out


def artifact(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "artifact_type": row["artifact_type"],
        "content_hash": row["content_hash"],
        "state": row["state"],
        "effective_from": fmt_ts(row["effective_from"]),
        "expires_at": fmt_ts(row["expires_at"]),
        "attested_by_user_id": row["attested_by_user_id"],
        "attested_at": fmt_ts(row["attested_at"]),
        "expired_reason": row["expired_reason"],
    }
    out.update(_common(row))
    return out


def terminal(row):
    out = {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "program_id": row["program_id"],
        "serial_number": row["serial_number"],
        "debit_exclusion_enabled": row["debit_exclusion_enabled"],
        "bin_table_version": row["bin_table_version"],
        "state": row["state"],
        "quarantine_reason": row["quarantine_reason"],
        "last_configured_at": fmt_ts(row["last_configured_at"]),
    }
    out.update(_common(row))
    return out


def transaction(row):
    # A captured sale is an immutable event: id and created_at only, no
    # updated_at and no version (PRD 2.4).
    return {
        "id": row["id"],
        "terminal_id": row["terminal_id"],
        "program_id": row["program_id"],
        "card_brand": row["card_brand"],
        "card_funding": row["card_funding"],
        "product_tier": row["product_tier"],
        "base_amount_cents": row["base_amount_cents"],
        "requested_surcharge_cents": row["requested_surcharge_cents"],
        "receipt_line_present": row["receipt_line_present"],
        "applied_rate_pct": row["applied_rate_pct"],
        "surcharge_amount_cents": row["surcharge_amount_cents"],
        "cash_discount_amount_cents": row["cash_discount_amount_cents"],
        "cash_price_cents": row["cash_price_cents"],
        "total_amount_cents": row["total_amount_cents"],
        "outcome": row["outcome"],
        "refunded_surcharge_cents": calc.refunded_surcharge_cents(row["id"]),
        "occurred_at": fmt_ts(row["occurred_at"]),
        "created_at": fmt_ts(row["created_at"]),
    }


def complaint_case(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "source": row["source"],
        "allegation_type": row["allegation_type"],
        "narrative": row["narrative"],
        "filed_by_user_id": row["filed_by_user_id"],
        "received_at": fmt_ts(row["received_at"]),
        "response_due_at": fmt_ts(row["response_due_at"]),
        "investigation_state": row["investigation_state"],
        "remediation_state": row["remediation_state"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "plan_summary": row["plan_summary"],
        "refund_total_cents": calc.case_refund_total(row["id"]),
    }
    out.update(_common(row))
    return out


def refund(row):
    out = {
        "id": row["id"],
        "complaint_case_id": row["complaint_case_id"],
        "transaction_id": row["transaction_id"],
        "refund_amount_cents": row["refund_amount_cents"],
        "state": row["state"],
        "created_by_user_id": row["created_by_user_id"],
        "issued_by_user_id": row["issued_by_user_id"],
        "issued_at": fmt_ts(row["issued_at"]),
        "voided_at": fmt_ts(row["voided_at"]),
    }
    out.update(_common(row))
    return out
