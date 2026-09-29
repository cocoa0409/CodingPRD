"""Row -> JSON serialisers. Every entity carries id, created_at, updated_at, version."""
from decimal import Decimal

import calc
from store import fmt_instant


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {"id": row["id"],
            "created_at": fmt_instant(row["created_at"]),
            "updated_at": fmt_instant(row["updated_at"]),
            "version": row["version"]}


def partner(row):
    # Derived fields are full recomputations from the current rows (PRD 2.9).
    calc.recompute_cert_credits(row)
    calc.recompute_revenue(row)
    calc.recompute_marketing(row)
    calc.recompute_conflicts(row)
    calc.recompute_entitlement(row)
    out = _common(row)
    out.update({
        "company_name": row["company_name"],
        "partner_type": row["partner_type"],
        "tier": row["tier"],
        "tier_status": row["tier_status"],
        "marketing_commitment_cents": row["marketing_commitment_cents"],
        "cert_credit_total": row["cert_credit_total"],
        "trailing_revenue_cents": row["trailing_revenue_cents"],
        "marketing_qualified_spend_cents": row["marketing_qualified_spend_cents"],
        "marketing_attainment_pct": _num(row["marketing_attainment_pct"]),
        "portal_entitlement_level": row["portal_entitlement_level"],
        "open_conflict_count": row["open_conflict_count"],
        "standing_reason": row["standing_reason"],
    })
    return out


def certification(row):
    out = _common(row)
    out.update({
        "partner_id": row["partner_id"],
        "engineer_name": row["engineer_name"],
        "track": row["track"],
        "credit_weight": row["credit_weight"],
        "status": row["status"],
        "issued_at": fmt_instant(row["issued_at"]),
        "expires_at": fmt_instant(row["expires_at"]),
    })
    return out


def account(row):
    out = _common(row)
    out.update({
        "account_name": row["account_name"],
        "region_code": row["region_code"],
        "coverage_state": row["coverage_state"],
        "protected_until": fmt_instant(row["protected_until"]),
        "protected_partner_id": row["protected_partner_id"],
        "protected_product_line": row["protected_product_line"],
        "direct_pursuit_owner_id": row["direct_pursuit_owner_id"],
        "direct_pursuit_declared_at": fmt_instant(row["direct_pursuit_declared_at"]),
    })
    return out


def mapping(row):
    out = _common(row)
    out.update({
        "partner_id": row["partner_id"],
        "account_id": row["account_id"],
        "product_line": row["product_line"],
        "exclusivity_scope": row["exclusivity_scope"],
        "effective_from": fmt_instant(row["effective_from"]),
        "effective_until": fmt_instant(row["effective_until"]),
        "mapping_status": row["mapping_status"],
        "counter_round": row["counter_round"],
        "activated_at": fmt_instant(row["activated_at"]),
        "closure_reason": row["closure_reason"],
    })
    return out


def registration(row):
    out = _common(row)
    out.update({
        "partner_id": row["partner_id"],
        "account_id": row["account_id"],
        "product_line": row["product_line"],
        "expected_amount_cents": row["expected_amount_cents"],
        "expected_close_date": fmt_instant(row["expected_close_date"]),
        "supersedes_registration_id": row["supersedes_registration_id"],
        "status": row["status"],
        "submitted_at": fmt_instant(row["submitted_at"]),
        "approved_at": fmt_instant(row["approved_at"]),
        "exclusivity_start_at": fmt_instant(row["exclusivity_start_at"]),
        "exclusivity_end_at": fmt_instant(row["exclusivity_end_at"]),
        "protection_days": row["protection_days"],
        "registration_margin_uplift_pct": _num(row["registration_margin_uplift_pct"]),
        "revision_round": row["revision_round"],
        "closure_reason": row["closure_reason"],
    })
    return out


def conflict(row):
    out = _common(row)
    out.update({
        "account_id": row["account_id"],
        "subject_registration_id": row["subject_registration_id"],
        "counter_registration_id": row["counter_registration_id"],
        "conflict_type": row["conflict_type"],
        "status": row["status"],
        "detected_at": fmt_instant(row["detected_at"]),
        "escalation_level": row["escalation_level"],
        "applied_variant": row["applied_variant"],
        "recommended_resolution": row["recommended_resolution"],
        "recommended_resolution_registration_first": row["recommended_resolution_registration_first"],
        "recommended_resolution_coverage_first": row["recommended_resolution_coverage_first"],
        "resolution_note": row["resolution_note"],
        "resolved_by_user_id": row["resolved_by_user_id"],
    })
    return out


def spr(row):
    out = _common(row)
    out.update({
        "registration_id": row["registration_id"],
        "requested_extra_margin_pct": _num(row["requested_extra_margin_pct"]),
        "justification": row["justification"],
        "status": row["status"],
        "approved_extra_margin_pct": _num(row["approved_extra_margin_pct"]),
        "expires_at": fmt_instant(row["expires_at"]),
        "decided_by_user_id": row["decided_by_user_id"],
    })
    return out


def allocation(row):
    calc.recompute_available(row)
    out = _common(row)
    out.update({
        "partner_id": row["partner_id"],
        "period_start": fmt_instant(row["period_start"]),
        "period_end": fmt_instant(row["period_end"]),
        "basis_revenue_cents": row["basis_revenue_cents"],
        "allocated_cents": row["allocated_cents"],
        "committed_cents": row["committed_cents"],
        "paid_cents": row["paid_cents"],
        "expired_cents": row["expired_cents"],
        "available_cents": row["available_cents"],
        "status": row["status"],
        "closed_at": fmt_instant(row["closed_at"]),
    })
    return out


def claim(row):
    out = _common(row)
    out.update({
        "allocation_id": row["allocation_id"],
        "activity_type": row["activity_type"],
        "requested_cents": row["requested_cents"],
        "validation_state": row["validation_state"],
        "settlement_state": row["settlement_state"],
        "matched_total_cents": row["matched_total_cents"],
        "approved_cents": row["approved_cents"],
        "proof_round": row["proof_round"],
        "validated_by_user_id": row["validated_by_user_id"],
        "settled_by_user_id": row["settled_by_user_id"],
        "rejection_reason": row["rejection_reason"],
    })
    return out


def proof(row):
    out = _common(row)
    out.update({
        "claim_id": row["claim_id"],
        "doc_type": row["doc_type"],
        "spend_amount_cents": row["spend_amount_cents"],
        "audience_reach": row["audience_reach"],
        "verified": row["verified"],
        "verified_at": fmt_instant(row["verified_at"]),
        "verified_by_user_id": row["verified_by_user_id"],
        "matched_line_cents": row["matched_line_cents"],
    })
    return out


def order(row):
    out = _common(row)
    out.update({
        "partner_id": row["partner_id"],
        "registration_id": row["registration_id"],
        "order_type": row["order_type"],
        "list_amount_cents": row["list_amount_cents"],
        "margin_pct": _num(row["margin_pct"]),
        "volume_band": row["volume_band"],
        "invoice_amount_cents": row["invoice_amount_cents"],
        "margin_value_cents": row["margin_value_cents"],
        "credit_memo_cents": row["credit_memo_cents"],
        "status": row["status"],
        "invoiced_at": fmt_instant(row["invoiced_at"]),
        "credit_reason": row["credit_reason"],
    })
    return out


def review(row):
    out = _common(row)
    out.update({
        "partner_id": row["partner_id"],
        "period_start": fmt_instant(row["period_start"]),
        "period_end": fmt_instant(row["period_end"]),
        "findings_count": row["findings_count"],
        "remediation_due_at": fmt_instant(row["remediation_due_at"]),
        "provisional_cert_credit": row["provisional_cert_credit"],
        "provisional_revenue_cents": row["provisional_revenue_cents"],
        "provisional_score": _num(row["provisional_score"]),
        "recommended_tier": row["recommended_tier"],
        "final_cert_credit": row["final_cert_credit"],
        "final_revenue_cents": row["final_revenue_cents"],
        "final_score": _num(row["final_score"]),
        "approved_tier": row["approved_tier"],
        "marketing_attainment_pct": _num(row["marketing_attainment_pct"]),
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "remediation_note": row["remediation_note"],
    })
    return out
