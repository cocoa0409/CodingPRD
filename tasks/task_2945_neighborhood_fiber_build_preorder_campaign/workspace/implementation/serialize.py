"""Resource representations. Every derived field is computed at this moment."""

import calc
from store import fmt_dt, rows


def _sys(row, versioned=True):
    out = {"created_at": fmt_dt(row["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(row["updated_at"])
        out["version"] = row["version"]
    return out


def campaign(row):
    zone_count = sum(1 for z in rows("build_zones") if z["campaign_id"] == row["id"])
    out = {
        "id": row["id"],
        "name": row["name"],
        "city": row["city"],
        "prereg_window_open_at": fmt_dt(row["prereg_window_open_at"]),
        "prereg_window_close_at": fmt_dt(row["prereg_window_close_at"]),
        "default_threshold_pct": calc.as_number(row["default_threshold_pct"]),
        "deposit_amount_cents": row["deposit_amount_cents"],
        "max_deadline_extensions": row["max_deadline_extensions"],
        "extension_grant_days": row["extension_grant_days"],
        "claim_filing_window_days": row["claim_filing_window_days"],
        "restoration_sla_days": row["restoration_sla_days"],
        "late_filing_factor": calc.as_number(row["late_filing_factor"]),
        "zone_count": zone_count,
    }
    out.update(_sys(row))
    return out


def build_zone(row):
    provisional_count, provisional_rate = calc.prereg_rate(row, "PROVISIONAL")
    out = {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "name": row["name"],
        "zone_code": row["zone_code"],
        "household_count": row["household_count"],
        "threshold_pct": calc.as_number(row["threshold_pct"]),
        "required_permit_types": list(row["required_permit_types"]),
        "max_concurrent_bury_ops": row["max_concurrent_bury_ops"],
        "prereg_deadline_at": fmt_dt(row["prereg_deadline_at"]),
        "extension_count": row["extension_count"],
        "cumulative_extension_days": row["cumulative_extension_days"],
        "campaign_status": row["campaign_status"],
        "construction_status": row["construction_status"],
        "suspension_reason": row["suspension_reason"],
        "provisional_qualifying_count": provisional_count,
        "prereg_rate_pct": calc.as_number(provisional_rate),
        "final_qualifying_count": row["final_qualifying_count"],
        "final_rate_pct": calc.as_number(row["final_rate_pct"]),
        "make_ready_cost_cents": calc.make_ready_cost(row),
        "readiness_score": calc.as_number(row["readiness_score"]),
        "readiness_posture": calc.readiness_posture(row),
        "build_sequence_index": row["build_sequence_index"],
        "outstanding_restoration_count": calc.outstanding_restoration_count(row),
    }
    out.update(_sys(row))
    return out


def service_address(row):
    out = {
        "id": row["id"],
        "build_zone_id": row["build_zone_id"],
        "street_address": row["street_address"],
        "dwelling_type": row["dwelling_type"],
        "unit_count": row["unit_count"],
        "distance_to_node_m": row["distance_to_node_m"],
        "serviceability": row["serviceability"],
        "not_serviceable_reason": row["not_serviceable_reason"],
        "serviceability_determined_at": fmt_dt(row["serviceability_determined_at"]),
        "exception_status": row["exception_status"],
        "exception_reason": row["exception_reason"],
        "active_fallback_technology": row["active_fallback_technology"],
        "counts_toward_threshold": calc.address_counts(row),
    }
    out.update(_sys(row))
    return out


def account(row):
    held, credit = calc.balances(row)
    out = {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "phone": row["phone"],
        "account_type": row["account_type"],
        "deposit_held_cents": held,
        "credit_balance_cents": credit,
    }
    out.update(_sys(row))
    return out


def mdu_agreement(row):
    out = {
        "id": row["id"],
        "service_address_id": row["service_address_id"],
        "owner_account_id": row["owner_account_id"],
        "status": row["status"],
        "access_fee_cents": row["access_fee_cents"],
        "countered_fee_cents": row["countered_fee_cents"],
        "offer_round": row["offer_round"],
        "counter_round": row["counter_round"],
        "max_counter_rounds": row["max_counter_rounds"],
        "expires_at": fmt_dt(row["expires_at"]),
        "signed_at": fmt_dt(row["signed_at"]),
    }
    out.update(_sys(row))
    return out


def permit_application(row):
    out = {
        "id": row["id"],
        "build_zone_id": row["build_zone_id"],
        "permit_type": row["permit_type"],
        "status": row["status"],
        "submission_round": row["submission_round"],
        "max_resubmissions": row["max_resubmissions"],
        "valid_days": row["valid_days"],
        "approved_at": fmt_dt(row["approved_at"]),
        "expires_at": fmt_dt(row["expires_at"]),
        "rejection_reason": row["rejection_reason"],
        "reviewer_user_id": row["reviewer_user_id"],
    }
    out.update(_sys(row))
    return out


def pole_request(row):
    out = {
        "id": row["id"],
        "build_zone_id": row["build_zone_id"],
        "utility_owner": row["utility_owner"],
        "pole_count": row["pole_count"],
        "status": row["status"],
        "make_ready_cost_cents": row["make_ready_cost_cents"],
        "survey_completed_at": fmt_dt(row["survey_completed_at"]),
        "denial_reason": row["denial_reason"],
        "attached_at": fmt_dt(row["attached_at"]),
    }
    out.update(_sys(row))
    return out


def preorder(row):
    out = {
        "id": row["id"],
        "build_zone_id": row["build_zone_id"],
        "service_address_id": row["service_address_id"],
        "account_id": row["account_id"],
        "plan_tier": row["plan_tier"],
        "unit_designator": row["unit_designator"],
        "preorder_status": row["preorder_status"],
        "deposit_status": row["deposit_status"],
        "deposit_amount_cents": row["deposit_amount_cents"],
        "counts_toward_threshold": calc.preorder_counts(row),
        "make_ready_share_cents": row["make_ready_share_cents"],
        "drop_method": row["drop_method"],
        "conversion_pre_discount_total_cents": row["conversion_pre_discount_total_cents"],
        "conversion_discount_cents": row["conversion_discount_cents"],
        "conversion_total_due_cents": row["conversion_total_due_cents"],
        "converted_at": fmt_dt(row["converted_at"]),
        "cancelled_at": fmt_dt(row["cancelled_at"]),
        "lapse_reason": row["lapse_reason"],
    }
    out.update(_sys(row))
    return out


def install_crew(row):
    minutes, count = calc.crew_booked(row)
    out = {
        "id": row["id"],
        "name": row["name"],
        "crew_type": row["crew_type"],
        "travel_buffer_minutes": row["travel_buffer_minutes"],
        "daily_capacity_minutes": row["daily_capacity_minutes"],
        "booked_minutes_total": minutes,
        "scheduled_appointment_count": count,
    }
    out.update(_sys(row))
    return out


def install_appointment(row):
    out = {
        "id": row["id"],
        "preorder_id": row["preorder_id"],
        "crew_id": row["crew_id"],
        "parent_appointment_id": row["parent_appointment_id"],
        "appointment_type": row["appointment_type"],
        "window_start_at": fmt_dt(row["window_start_at"]),
        "window_end_at": fmt_dt(row["window_end_at"]),
        "status": row["status"],
        "occupied_minutes": row["occupied_minutes"],
        "restoration_required": row["restoration_required"],
        "restoration_due_by": fmt_dt(row["restoration_due_by"]),
        "restoration_satisfied_at": fmt_dt(row["restoration_satisfied_at"]),
        "completed_at": fmt_dt(row["completed_at"]),
        "cancellation_reason": row["cancellation_reason"],
    }
    out.update(_sys(row))
    return out


def damage_claim(row):
    out = {
        "id": row["id"],
        "install_appointment_id": row["install_appointment_id"],
        "service_address_id": row["service_address_id"],
        "claimant_account_id": row["claimant_account_id"],
        "damage_type": row["damage_type"],
        "claimed_amount_cents": row["claimed_amount_cents"],
        "description": row["description"],
        "status": row["status"],
        "filed_at": fmt_dt(row["filed_at"]),
        "assessed_amount_cents": row["assessed_amount_cents"],
        "assessment_variant": row["assessment_variant"],
        "assessed_by_user_id": row["assessed_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "appeal_count": row["appeal_count"],
        "max_appeals": row["max_appeals"],
        "denial_reason": row["denial_reason"],
        "paid_at": fmt_dt(row["paid_at"]),
    }
    out.update(_sys(row))
    return out


def ledger_entry(row):
    out = {
        "id": row["id"],
        "account_id": row["account_id"],
        "preorder_id": row["preorder_id"],
        "damage_claim_id": row["damage_claim_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "memo": row["memo"],
        "occurred_at": fmt_dt(row["occurred_at"]),
    }
    out.update(_sys(row, versioned=False))
    return out


def fallback_option(row):
    out = {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "technology": row["technology"],
        "min_downstream_mbps": row["min_downstream_mbps"],
        "monthly_price_cents": row["monthly_price_cents"],
        "max_serviceable_distance_m": row["max_serviceable_distance_m"],
        "supports_mdu": row["supports_mdu"],
        "priority_rank": row["priority_rank"],
        "option_status": row["option_status"],
    }
    out.update(_sys(row))
    return out


def fallback_offer(row):
    out = {
        "id": row["id"],
        "service_address_id": row["service_address_id"],
        "fallback_option_id": row["fallback_option_id"],
        "account_id": row["account_id"],
        "status": row["status"],
        "technology": row["technology"],
        "min_downstream_mbps": row["min_downstream_mbps"],
        "monthly_price_cents": row["monthly_price_cents"],
        "offered_at": fmt_dt(row["offered_at"]),
        "expires_at": fmt_dt(row["expires_at"]),
        "responded_at": fmt_dt(row["responded_at"]),
    }
    out.update(_sys(row))
    return out
