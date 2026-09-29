"""Wire representations. Field names come verbatim from SCAFFOLD §1.1; derived
properties are recomputed at serialization so a read always reflects the
current picture (PRD §2.10, §3.1)."""

from core import *  # noqa: F401,F403
from logic import (
    account_history, account_rebooking_tier, block_allotted_room_nights,
    block_comp_room_nights, block_peak_night_rooms, block_picked_up_room_nights,
    block_released_room_nights, night_rooms_open, night_rooms_picked_up,
    night_rooms_sub_allocated, posted_ancillary_cents,
)


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def account_json(row):
    repeat_count, lifetime, last_departure = account_history(row["id"])
    out = _common(row)
    out.update({
        "name": row["name"],
        "market_segment": row["market_segment"],
        "billing_contact_email": row["billing_contact_email"],
        "credit_hold": row["credit_hold"],
        "repeat_group_count": repeat_count,
        "lifetime_actualized_room_nights": lifetime,
        "last_completed_departure_date": last_departure,
        "rebooking_incentive_pct": account_rebooking_tier(
            repeat_count, lifetime, last_departure),
    })
    return out


def lead_json(row):
    out = _common(row)
    out.update({
        "account_id": row["account_id"],
        "owner_user_id": row["owner_user_id"],
        "program_name": row["program_name"],
        "arrival_date": row["arrival_date"],
        "departure_date": row["departure_date"],
        "nights_count": row["nights_count"],
        "peak_rooms": row["peak_rooms"],
        "total_requested_room_nights": row["total_requested_room_nights"],
        "meeting_space_sqft_needed": row["meeting_space_sqft_needed"],
        "decision_deadline_at": row["decision_deadline_at"],
        "status": row["status"],
        "qualification_score": row["qualification_score"],
        "estimated_room_night_value_cents": row["estimated_room_night_value_cents"],
    })
    return out


def inventory_day_json(row):
    out = _common(row)
    out.update({
        "stay_date": row["stay_date"],
        "total_rooms": row["total_rooms"],
        "group_ceiling_rooms": row["group_ceiling_rooms"],
        "transient_demand_rooms": row["transient_demand_rooms"],
        "transient_adr_cents": row["transient_adr_cents"],
        "historical_pickup_rooms": row["historical_pickup_rooms"],
        "historical_adr_cents": row["historical_adr_cents"],
        "held_group_rooms": row["held_group_rooms"],
        "committed_group_rooms": row["committed_group_rooms"],
    })
    return out


def package_json(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "room_rate_discount_pct": row["room_rate_discount_pct"],
        "comp_room_ratio": row["comp_room_ratio"],
        "rebate_per_room_night_cents": row["rebate_per_room_night_cents"],
        "banquet_discount_pct": row["banquet_discount_pct"],
        "av_discount_pct": row["av_discount_pct"],
        "parking_discount_pct": row["parking_discount_pct"],
        "min_peak_rooms": row["min_peak_rooms"],
        "min_total_room_nights": row["min_total_room_nights"],
        "max_discount_stack_pct": row["max_discount_stack_pct"],
        "discount_stack_pct": row["discount_stack_pct"],
    })
    return out


def analysis_json(row):
    out = _common(row)
    out.update({
        "lead_id": row["lead_id"],
        "analysis_variant": row["analysis_variant"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "status": row["status"],
        "verdict": row["verdict"],
        "displaced_room_nights": row["displaced_room_nights"],
        "displaced_revenue_cents": row["displaced_revenue_cents"],
        "group_revenue_cents": row["group_revenue_cents"],
        "ancillary_projection_cents": row["ancillary_projection_cents"],
        "net_benefit_cents": row["net_benefit_cents"],
        "override_reason": row["override_reason"],
    })
    return out


def quote_json(row):
    out = _common(row)
    out.update({
        "lead_id": row["lead_id"],
        "concession_package_id": row["concession_package_id"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "negotiation_round": row["negotiation_round"],
        "status": row["status"],
        "base_rate_cents": row["base_rate_cents"],
        "quoted_peak_rooms": row["quoted_peak_rooms"],
        "quoted_room_nights": row["quoted_room_nights"],
        "comp_room_ratio": row["comp_room_ratio"],
        "rebate_per_room_night_cents": row["rebate_per_room_night_cents"],
        "effective_net_rate_cents": row["effective_net_rate_cents"],
        "total_quote_value_cents": row["total_quote_value_cents"],
        "expires_at": row["expires_at"],
        "hold_placed": row["hold_placed"],
        "countered_base_rate_cents": row["countered_base_rate_cents"],
        "counter_note": row["counter_note"],
    })
    return out


def contract_json(row):
    out = _common(row)
    posted = posted_ancillary_cents(row["id"])
    out.update({
        "quote_id": row["quote_id"],
        "status": row["status"],
        "attrition_threshold_pct": row["attrition_threshold_pct"],
        "attrition_basis": row["attrition_basis"],
        "force_majeure_clause": row["force_majeure_clause"],
        "cutoff_days_before_arrival": row["cutoff_days_before_arrival"],
        "contracted_room_nights": row["contracted_room_nights"],
        "contracted_peak_rooms": row["contracted_peak_rooms"],
        "nightly_allotments": [dict(entry) for entry in row["nightly_allotments"]],
        "contracted_rate_cents": row["contracted_rate_cents"],
        "arrival_date": row["arrival_date"],
        "departure_date": row["departure_date"],
        "nights_count": row["nights_count"],
        "signed_by_user_id": row["signed_by_user_id"],
        "signed_at": row["signed_at"],
        "signature_name": row["signature_name"],
        "cancellation_reason": row["cancellation_reason"],
        "assessed_damages_cents": row["assessed_damages_cents"],
        "ancillary_posted_cents": posted,
        "rebate_paid_cents": row["rebate_paid_cents"],
        "receivable_total_cents": (posted + row["assessed_damages_cents"]
                                   - row["rebate_paid_cents"]),
    })
    return out


def block_json(row):
    out = _common(row)
    out.update({
        "contract_id": row["contract_id"],
        "parent_block_id": row["parent_block_id"],
        "name": row["name"],
        "is_master": row["parent_block_id"] is None,
        "inventory_status": row["inventory_status"],
        "billing_status": row["billing_status"],
        "cutoff_date": row["cutoff_date"],
        "allotted_room_nights": block_allotted_room_nights(row),
        "picked_up_room_nights": block_picked_up_room_nights(row),
        "released_room_nights": block_released_room_nights(row),
        "peak_night_rooms": block_peak_night_rooms(row),
        "comp_room_nights": block_comp_room_nights(row),
        "waived_by_user_id": row["waived_by_user_id"],
        "waiver_reason": row["waiver_reason"],
    })
    return out


def night_json(row):
    out = _common(row)
    out.update({
        "block_id": row["block_id"],
        "stay_date": row["stay_date"],
        "rooms_allotted": row["rooms_allotted"],
        "rooms_sub_allocated": night_rooms_sub_allocated(row),
        "rooms_picked_up": night_rooms_picked_up(row),
        "rooms_released": row["rooms_released"],
        "rooms_open": night_rooms_open(row),
    })
    return out


def reservation_json(row):
    out = _common(row)
    out.update({
        "block_id": row["block_id"],
        "guest_name": row["guest_name"],
        "arrival_date": row["arrival_date"],
        "departure_date": row["departure_date"],
        "source": row["source"],
        "room_nights": row["room_nights"],
        "is_comp": row["is_comp"],
        "rate_cents": row["rate_cents"],
        "status": row["status"],
        "disposition_reason": row["disposition_reason"],
    })
    return out


def charge_json(row):
    out = _common(row)
    out.update({
        "contract_id": row["contract_id"],
        "category": row["category"],
        "gross_amount_cents": row["gross_amount_cents"],
        "discount_pct": row["discount_pct"],
        "net_amount_cents": row["net_amount_cents"],
        "status": row["status"],
    })
    return out


def reconciliation_json(row):
    out = _common(row)
    out.update({
        "contract_id": row["contract_id"],
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "finalized_by_user_id": row["finalized_by_user_id"],
        "actualized_room_nights": row["actualized_room_nights"],
        "billable_room_nights": row["billable_room_nights"],
        "attrition_shortfall_room_nights": row["attrition_shortfall_room_nights"],
        "attrition_damages_cents": row["attrition_damages_cents"],
        "ancillary_net_cents": row["ancillary_net_cents"],
        "gross_settlement_cents": row["gross_settlement_cents"],
        "rebate_payable_cents": row["rebate_payable_cents"],
        "net_before_incentive_cents": row["net_before_incentive_cents"],
        "incentive_rate_snapshot": row["incentive_rate_snapshot"],
        "rebooking_incentive_cents": row["rebooking_incentive_cents"],
        "total_settlement_cents": row["total_settlement_cents"],
    })
    return out


def hold_json(row):
    out = _common(row)
    out.update({
        "lead_id": row["lead_id"],
        "space_code": row["space_code"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "attendee_count": row["attendee_count"],
        "status": row["status"],
    })
    return out
