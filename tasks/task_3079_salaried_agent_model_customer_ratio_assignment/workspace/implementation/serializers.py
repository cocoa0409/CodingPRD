"""Public JSON projections. Internal `_`-prefixed bookkeeping never leaves."""

from calculations import access_code_visible
from utils import iso_z


def region(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "name": row["name"],
        "service_area_codes": list(row["service_area_codes"]),
        "traditional_commission_pct": row["traditional_commission_pct"],
        "target_client_ratio": row["target_client_ratio"],
        "agent_count": row["agent_count"],
        "occupancy_pct": row["occupancy_pct"],
        "occupancy_band": row["occupancy_band"],
        "clients_in_pipeline": row["clients_in_pipeline"],
        "referral_count": row["referral_count"],
        "open_referral_count": row["open_referral_count"],
        "enrolment_is_required": row["enrolment_is_required"],
        "capacity": row["capacity"],
    }


def agent(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "region_id": row["region_id"],
        "full_name": row["full_name"],
        "agent_kind": row["agent_kind"],
        "home_zip": row["home_zip"],
        "base_salary_cents": row["base_salary_cents"],
        "benefits_cents": row["benefits_cents"],
        "expense_allowance_cents": row["expense_allowance_cents"],
        "satisfaction_score": row["satisfaction_score"],
        "close_rate": row["close_rate"],
        "bonus_pct": row["bonus_pct"],
        "bonus_cents": row["bonus_cents"],
        "salary_commitment_cents": row["salary_commitment_cents"],
        "open_referral_count": row["open_referral_count"],
        "referral_fee_bps": row["referral_fee_bps"],
        "status": row["status"],
    }


def open_client_count(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "agent_id": row["agent_id"],
        "active_client_count": row["active_client_count"],
        "ratio_state": row["ratio_state"],
    }


def lead_capacity(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "agent_id": row["agent_id"],
        "current_state": row["current_state"],
        "tours_in_week": row["tours_in_week"],
        "associate_capacity_used": row["associate_capacity_used"],
        "close_rate": row["close_rate"],
        "graded_transactions": row["graded_transactions"],
        "trailing_tours": row["trailing_tours"],
        "unassigned_tours": row["unassigned_tours"],
    }


def client(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "region_id": row["region_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "service_area_code": row["service_area_code"],
        "need_kind": row["need_kind"],
        "assigned_agent_id": row["assigned_agent_id"],
        "assignment_mode": row["assignment_mode"],
        "assignment_reason": row["assignment_reason"],
        "status": row["status"],
    }


def transaction(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "client_id": row["client_id"],
        "lead_agent_id": row["lead_agent_id"],
        "coordination_status": row["coordination_status"],
        "contract_price_cents": row["contract_price_cents"],
        "closed_at": row["closed_at"],
        "agent_satisfaction_credit": row["agent_satisfaction_credit"],
    }


def listing(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "region_id": row["region_id"],
        "client_id": row["client_id"],
        "list_price_cents": row["list_price_cents"],
        "list_fee_rate_pct": row["list_fee_rate_pct"],
        "service_tier": row["service_tier"],
        "traditional_listing_fee_cents": row["traditional_listing_fee_cents"],
        "partner_referral_fee_cents": row["partner_referral_fee_cents"],
        "gross_listing_fee_cents": row["gross_listing_fee_cents"],
        "savings_amount_cents": row["savings_amount_cents"],
        "savings_pct": row["savings_pct"],
        "final_listing_fee_cents": row["final_listing_fee_cents"],
        "service_commitment_hours": row["service_commitment_hours"],
        "posted_at": row["posted_at"],
        "status": row["status"],
    }


def tour(row):
    visible = access_code_visible(row["_scheduled_at"])
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "lead_agent_id": row["lead_agent_id"],
        "client_id": row["client_id"],
        "listing_agreement_id": row["listing_agreement_id"],
        "associate_agent_id": row["associate_agent_id"],
        "scheduled_at": iso_z(row["_scheduled_at"]),
        "access_instructions": row["access_instructions"],
        "access_code": row["access_code"] if visible else None,
        "status": row["status"],
        "feedback_rating": row["feedback_rating"],
        "feedback_notes": row["feedback_notes"],
        "tours_next_36_hours": row["tours_next_36_hours"],
    }


def survey(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "transaction_id": row["transaction_id"],
        "agent_id": row["agent_id"],
        "score": row["score"],
        "response_status": row["response_status"],
        "bonus_eligible": row["bonus_eligible"],
        "dispatched_at": row["dispatched_at"],
        "responded_at": row["responded_at"],
    }


def referral(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "region_id": row["region_id"],
        "client_id": row["client_id"],
        "partner_name": row["partner_name"],
        "referral_fee_bps": row["referral_fee_bps"],
        "referral_fee_cents": row["referral_fee_cents"],
        "settlement_status": row["settlement_status"],
        "split_policy": row["split_policy"],
        "partner_cents": row["partner_cents"],
        "house_cents": row["house_cents"],
        "settlement_reference": row["settlement_reference"],
    }


def activity_audit(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "region_id": row["region_id"],
        "entity_type": row["entity_type"],
        "entity_ref_id": row["entity_ref_id"],
        "kind": row["kind"],
        "detail": row["detail"],
    }