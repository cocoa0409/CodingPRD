"""JSON projections for every entity, with derived fields computed on read."""

from decimal import Decimal

import store
from services import ledger


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, body):
    out = {"id": row["id"]}
    out.update(body)
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def jurisdiction(row):
    return _common(row, {
        "code": row["code"],
        "name": row["name"],
        "hazard_tier": row["hazard_tier"],
        "admin_agency_name": row["admin_agency_name"],
        "pre_suit_mediation_required": row["pre_suit_mediation_required"],
        "pre_suit_window_days": row["pre_suit_window_days"],
        "wage_hour_multiplier": num(row["wage_hour_multiplier"]),
        "class_action_propensity_pct": num(row["class_action_propensity_pct"]),
    })


def rate_plan(row):
    return _common(row, {
        "name": row["name"],
        "base_rate_per_employee_cents": row["base_rate_per_employee_cents"],
        "min_premium_cents": row["min_premium_cents"],
        "wage_hour_sublimit_pct": num(row["wage_hour_sublimit_pct"]),
        "third_party_sublimit_pct": num(row["third_party_sublimit_pct"]),
        "status": row["status"],
    })


def applicant(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "total_headcount": row["total_headcount"],
        "prior_year_separations": row["prior_year_separations"],
        "separations_since_assessment": row["separations_since_assessment"],
        "jurisdiction_headcounts": [
            {"code": e["code"], "headcount": e["headcount"]}
            for e in row["jurisdiction_headcounts"]],
        "primary_jurisdiction_code": row["primary_jurisdiction_code"],
        "turnover_pct": num(row["turnover_pct"]),
        "hazard_load_pct": num(row["hazard_load_pct"]),
        "risk_credit_pct": num(row["risk_credit_pct"]),
        "exposure_score": num(row["exposure_score"]),
    })


def service(row):
    return _common(row, {
        "applicant_id": row["applicant_id"],
        "service_type": row["service_type"],
        "credit_pct": num(row["credit_pct"]),
        "effective_from": store.fmt_instant(row["effective_from"]),
        "effective_to": store.fmt_instant(row["effective_to"]),
        "completed_at": store.fmt_instant(row["completed_at"]),
        "revocation_reason": row["revocation_reason"],
        "status": row["status"],
    })


def assessment(row):
    return _common(row, {
        "applicant_id": row["applicant_id"],
        "rate_plan_id": row["rate_plan_id"],
        "requested_aggregate_limit_cents": row["requested_aggregate_limit_cents"],
        "requested_retention_cents": row["requested_retention_cents"],
        "third_party_coverage_requested": row["third_party_coverage_requested"],
        "priced_by_user_id": row["priced_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "rejection_reason": row["rejection_reason"],
        "exposure_score_snapshot": num(row["exposure_score_snapshot"]),
        "turnover_pct_snapshot": num(row["turnover_pct_snapshot"]),
        "base_premium_cents": row["base_premium_cents"],
        "turnover_load_cents": row["turnover_load_cents"],
        "hazard_load_cents": row["hazard_load_cents"],
        "limit_load_cents": row["limit_load_cents"],
        "retention_credit_cents": row["retention_credit_cents"],
        "risk_mgmt_credit_cents": row["risk_mgmt_credit_cents"],
        "indicated_premium_cents": row["indicated_premium_cents"],
        "credit_basis_stale": row["credit_basis_stale"],
        "status": row["status"],
    })


def policy(row):
    return _common(row, {
        "applicant_id": row["applicant_id"],
        "exposure_assessment_id": row["exposure_assessment_id"],
        "effective_from": store.fmt_instant(row["effective_from"]),
        "effective_to": store.fmt_instant(row["effective_to"]),
        "aggregate_limit_cents": row["aggregate_limit_cents"],
        "per_claim_retention_cents": row["per_claim_retention_cents"],
        "third_party_coverage_elected": row["third_party_coverage_elected"],
        "wage_hour_sublimit_cents": row["wage_hour_sublimit_cents"],
        "third_party_sublimit_cents": row["third_party_sublimit_cents"],
        "bound_premium_cents": row["bound_premium_cents"],
        "premium_variance_cents": row["premium_variance_cents"],
        "indemnity_paid_cents": ledger.policy_indemnity_paid(row),
        "defense_spend_cents": ledger.policy_defense_spend(row),
        "aggregate_limit_remaining_cents": ledger.policy_remaining(row),
        "wage_hour_sublimit_remaining_cents":
            ledger.policy_wage_hour_remaining(row),
        "third_party_sublimit_remaining_cents":
            ledger.policy_third_party_remaining(row),
        "suspension_reason": row["suspension_reason"],
        "suspended_at": store.fmt_instant(row["suspended_at"]),
        "status": row["status"],
        "limit_posture": ledger.policy_limit_posture(row),
    })


def claim(row):
    return _common(row, {
        "policy_id": row["policy_id"],
        "claim_type": row["claim_type"],
        "claimant_class": row["claimant_class"],
        "notice_type": row["notice_type"],
        "first_notice_at": store.fmt_instant(row["first_notice_at"]),
        "alleged_damages_cents": row["alleged_damages_cents"],
        "claimant_count": row["claimant_count"],
        "related_to_claim_id": row["related_to_claim_id"],
        "related_claim_group_id": row["related_claim_group_id"],
        "coverage_bucket": row["coverage_bucket"],
        "retention_basis": ledger.claim_retention_basis(row),
        "per_claim_retention_cents": row["per_claim_retention_cents"],
        "pre_suit_credit_cents": row["pre_suit_credit_cents"],
        "applied_retention_cents": ledger.claim_applied_retention(row),
        "retention_satisfied_cents": ledger.claim_retention_satisfied(row),
        "indemnity_paid_cents": ledger.claim_indemnity_paid(row),
        "defense_paid_cents": ledger.claim_defense_paid(row),
        "reopen_count": row["reopen_count"],
        "coverage_gated": row["coverage_gated"],
        "denial_reason": row["denial_reason"],
        "status": row["status"],
    })


def group(row):
    return _common(row, {
        "policy_id": row["policy_id"],
        "lead_claim_id": row["lead_claim_id"],
        "aggregation_basis": row["aggregation_basis"],
        "member_count": len(store.members_of_group(row["id"])),
        "retention_basis_claim_id": ledger.group_retention_basis_claim_id(row),
        "shared_retention_cents": ledger.group_shared_retention(row),
        "retention_paid_cents": ledger.group_retention_paid(row),
        "status": row["status"],
    })


def firm(row):
    return _common(row, {
        "name": row["name"],
        "tier": row["tier"],
        "jurisdiction_codes": list(row["jurisdiction_codes"]),
        "partner_rate_cents_per_hour": row["partner_rate_cents_per_hour"],
        "associate_rate_cents_per_hour": row["associate_rate_cents_per_hour"],
        "paralegal_rate_cents_per_hour": row["paralegal_rate_cents_per_hour"],
        "capacity_open_matters": row["capacity_open_matters"],
        "blended_rate_cents": row["blended_rate_cents"],
        "open_matter_count": ledger.firm_open_matter_count(row),
        "status": row["status"],
    })


def assignment(row):
    return _common(row, {
        "claim_id": row["claim_id"],
        "panel_firm_id": row["panel_firm_id"],
        "engagement_from": store.fmt_instant(row["engagement_from"]),
        "engagement_to": store.fmt_instant(row["engagement_to"]),
        "partner_rate_cents_per_hour": row["partner_rate_cents_per_hour"],
        "associate_rate_cents_per_hour": row["associate_rate_cents_per_hour"],
        "paralegal_rate_cents_per_hour": row["paralegal_rate_cents_per_hour"],
        "litigation_guideline_version": row["litigation_guideline_version"],
        "budget_cap_cents": row["budget_cap_cents"],
        "budget_spent_cents": ledger.assignment_budget_spent(row),
        "budget_remaining_cents": ledger.assignment_budget_remaining(row),
        "selection_reason": row["selection_reason"],
        "hold_reason": row["hold_reason"],
        "funding_ceased_at": store.fmt_instant(row["funding_ceased_at"]),
        "status": row["status"],
    })


def invoice(row):
    return _common(row, {
        "defense_assignment_id": row["defense_assignment_id"],
        "period_start": store.fmt_instant(row["period_start"]),
        "period_end": store.fmt_instant(row["period_end"]),
        "partner_hours": num(row["partner_hours"]),
        "associate_hours": num(row["associate_hours"]),
        "paralegal_hours": num(row["paralegal_hours"]),
        "block_billed_hours": num(row["block_billed_hours"]),
        "expenses_cents": row["expenses_cents"],
        "dispute_note": row["dispute_note"],
        "billed_fees_cents": row["billed_fees_cents"],
        "rate_cap_excess_cents": row["rate_cap_excess_cents"],
        "block_reduction_cents": row["block_reduction_cents"],
        "expense_disallowance_cents": row["expense_disallowance_cents"],
        "guideline_reduction_cents": row["guideline_reduction_cents"],
        "allowed_amount_cents": row["allowed_amount_cents"],
        "disallowed_amount_cents": row["disallowed_amount_cents"],
        "audited_by_user_id": row["audited_by_user_id"],
        "void_reason": row["void_reason"],
        "hold_reason": row["hold_reason"],
        "status": row["status"],
    })


def payment(row):
    return _common(row, {
        "claim_id": row["claim_id"],
        "amount_cents": row["amount_cents"],
        "payment_basis": row["payment_basis"],
        "retention_portion_cents": row["retention_portion_cents"],
        "insurer_portion_cents": row["insurer_portion_cents"],
        "sublimit_bucket": row["sublimit_bucket"],
        "created_by_user_id": row["created_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "void_reason": row["void_reason"],
        "status": row["status"],
    })


def resolution(row):
    return _common(row, {
        "claim_id": row["claim_id"],
        "mediation_offered_at": store.fmt_instant(row["mediation_offered_at"]),
        "offer_expires_at": store.fmt_instant(row["offer_expires_at"]),
        "settlement_offer_cents": row["settlement_offer_cents"],
        "elapsed_days_at_accept": row["elapsed_days_at_accept"],
        "incentive_credit_cents": row["incentive_credit_cents"],
        "status": row["status"],
    })
