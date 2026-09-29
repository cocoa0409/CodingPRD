"""Output shapes.  Money is rendered with two decimals, instants with exactly
three fractional digits, dates as YYYY-MM-DD (PRD 2.4, 2.5).

The five append-only kinds -- support letters, incentive decisions, economic
impact estimates, nightly pickup records and lodging tax receipts -- expose only
`id` and `created_at`: `updated_at` and `version` are absent entirely.
"""

from util import format_date, format_instant, money_out


def _tail(row, out, versioned=True):
    out["created_at"] = format_instant(row["created_at"])
    if versioned:
        out["updated_at"] = format_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def planner(row):
    return _tail(row, {
        "id": row["id"],
        "org_name": row["org_name"],
        "contact_email": row["contact_email"],
        "legacy_definite_count": row["legacy_definite_count"],
        "legacy_definite_room_nights": row["legacy_definite_room_nights"],
        "definite_count": row["definite_count"],
        "lost_count": row["lost_count"],
        "lifetime_definite_room_nights": row["lifetime_definite_room_nights"],
        "relationship_score_lifetime": row["relationship_score_lifetime"],
        "relationship_score_rolling_24m": row["relationship_score_rolling_24m"],
        "tier": row["tier"],
        "engagement_status": row["engagement_status"],
        "last_touch_at": format_instant(row["last_touch_at"]),
    })


def hotel(row):
    return _tail(row, {
        "id": row["id"],
        "name": row["name"],
        "committable_rooms": row["committable_rooms"],
        "walk_distance_blocks": row["walk_distance_blocks"],
        "participation_status": row["participation_status"],
        "committed_peak_rooms": row["committed_peak_rooms"],
        "committed_room_nights": row["committed_room_nights"],
        "pickup_room_nights": row["pickup_room_nights"],
    })


def hall(row):
    return _tail(row, {
        "id": row["id"],
        "name": row["name"],
        "exhibit_sqft": row["exhibit_sqft"],
        "capacity_persons": row["capacity_persons"],
        "turnaround_hours": row["turnaround_hours"],
        "hall_status": row["hall_status"],
        "confirmed_hold_count": row["confirmed_hold_count"],
    })


def opportunity(row):
    return _tail(row, {
        "id": row["id"],
        "planner_id": row["planner_id"],
        "supersedes_opportunity_id": row["supersedes_opportunity_id"],
        "event_name": row["event_name"],
        "arrival_date": format_date(row["arrival_date"]),
        "departure_date": format_date(row["departure_date"]),
        "event_nights": row["event_nights"],
        "peak_rooms_requested": row["peak_rooms_requested"],
        "total_room_nights_requested": row["total_room_nights_requested"],
        "attendance_estimate": row["attendance_estimate"],
        "exhibit_sqft_requested": row["exhibit_sqft_requested"],
        "rate_ceiling_amount": money_out(row["rate_ceiling_amount"]),
        "sales_stage": row["sales_stage"],
        "hold_posture": row["hold_posture"],
        "committed_peak_rooms": row["committed_peak_rooms"],
        "block_coverage_pct": money_out(row["block_coverage_pct"]),
        "citywide_cutoff_days_before_arrival": row["citywide_cutoff_days_before_arrival"],
        "cutoff_alignment_spread_days": row["cutoff_alignment_spread_days"],
        "definite_room_nights": row["definite_room_nights"],
        "definite_at": format_instant(row["definite_at"]),
        "lost_reason": row["lost_reason"],
        "attrition_settlement_amount": money_out(row["attrition_settlement_amount"]),
    })


def space_hold(row):
    return _tail(row, {
        "id": row["id"],
        "opportunity_id": row["opportunity_id"],
        "center_hall_id": row["center_hall_id"],
        "challenged_by_space_hold_id": row["challenged_by_space_hold_id"],
        "move_in_start": format_instant(row["move_in_start"]),
        "move_out_end": format_instant(row["move_out_end"]),
        "hold_rank": row["hold_rank"],
        "status": row["status"],
        "expires_at": format_instant(row["expires_at"]),
        "challenge_deadline": format_instant(row["challenge_deadline"]),
        "release_reason": row["release_reason"],
    })


def commitment(row):
    return _tail(row, {
        "id": row["id"],
        "opportunity_id": row["opportunity_id"],
        "hotel_id": row["hotel_id"],
        "rooms_peak_invited": row["rooms_peak_invited"],
        "rooms_peak_offered": row["rooms_peak_offered"],
        "rooms_peak_committed": row["rooms_peak_committed"],
        "rate_offered_amount": money_out(row["rate_offered_amount"]),
        "cutoff_days_before_arrival": row["cutoff_days_before_arrival"],
        "cutoff_date": format_date(row["cutoff_date"]),
        "offer_round": row["offer_round"],
        "status": row["status"],
        "committed_room_nights": row["committed_room_nights"],
        "picked_up_room_nights": row["picked_up_room_nights"],
        "attrition_shortfall_nights": row["attrition_shortfall_nights"],
        "attrition_damages_amount": money_out(row["attrition_damages_amount"]),
        "withdraw_reason": row["withdraw_reason"],
    })


def bid_package(row):
    return _tail(row, {
        "id": row["id"],
        "opportunity_id": row["opportunity_id"],
        "round_number": row["round_number"],
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "incentive_requested_by_user_id": row["incentive_requested_by_user_id"],
        "incentive_request_amount": money_out(row["incentive_request_amount"]),
        "incentive_cap_amount": money_out(row["incentive_cap_amount"]),
        "service_commitment_codes": list(row["service_commitment_codes"]),
        "support_letter_type_count": row["support_letter_type_count"],
        "approved_incentive_amount": money_out(row["approved_incentive_amount"]),
        "admin_fee_amount": money_out(row["admin_fee_amount"]),
        "total_fund_charge_amount": money_out(row["total_fund_charge_amount"]),
        "tax_payback_ratio": money_out(row["tax_payback_ratio"]),
        "submitted_at": format_instant(row["submitted_at"]),
        "response_due_at": format_instant(row["response_due_at"]),
        "planner_response": row["planner_response"],
        "decline_reason": row["decline_reason"],
    })


def support_letter(row):
    return _tail(row, {
        "id": row["id"],
        "bid_package_id": row["bid_package_id"],
        "organization_name": row["organization_name"],
        "letter_type": row["letter_type"],
        "received_at": format_instant(row["received_at"]),
    }, versioned=False)


def fund(row):
    return _tail(row, {
        "id": row["id"],
        "fiscal_year": row["fiscal_year"],
        "budget_amount": money_out(row["budget_amount"]),
        "lodging_tax_receipts_total": money_out(row["lodging_tax_receipts_total"]),
        "committed_amount": money_out(row["committed_amount"]),
        "disbursed_amount": money_out(row["disbursed_amount"]),
        "uncommitted_amount": money_out(row["uncommitted_amount"]),
        "posture": row["posture"],
    })


def receipt(row):
    return _tail(row, {
        "id": row["id"],
        "fund_id": row["fund_id"],
        "amount": money_out(row["amount"]),
        "received_at": format_instant(row["received_at"]),
    }, versioned=False)


def decision(row):
    return _tail(row, {
        "id": row["id"],
        "bid_package_id": row["bid_package_id"],
        "fund_id": row["fund_id"],
        "decision": row["decision"],
        "requested_amount": money_out(row["requested_amount"]),
        "approved_amount": money_out(row["approved_amount"]),
        "admin_fee_amount": money_out(row["admin_fee_amount"]),
        "total_charge_amount": money_out(row["total_charge_amount"]),
        "tax_payback_ratio": money_out(row["tax_payback_ratio"]),
        "decided_by_user_id": row["decided_by_user_id"],
        "rationale": row["rationale"],
    }, versioned=False)


def estimate(row):
    return _tail(row, {
        "id": row["id"],
        "opportunity_id": row["opportunity_id"],
        "variant": row["variant"],
        "room_nights_basis": row["room_nights_basis"],
        "lodging_spend_amount": money_out(row["lodging_spend_amount"]),
        "delegate_spend_amount": money_out(row["delegate_spend_amount"]),
        "exhibitor_spend_amount": money_out(row["exhibitor_spend_amount"]),
        "direct_spend_amount": money_out(row["direct_spend_amount"]),
        "total_impact_amount": money_out(row["total_impact_amount"]),
        "lodging_tax_yield_amount": money_out(row["lodging_tax_yield_amount"]),
        "computed_at": format_instant(row["computed_at"]),
    }, versioned=False)


def servicing_order(row):
    return _tail(row, {
        "id": row["id"],
        "opportunity_id": row["opportunity_id"],
        "category": row["category"],
        "requested_units": row["requested_units"],
        "assigned_units": row["assigned_units"],
        "delivered_units": row["delivered_units"],
        "window_start": format_instant(row["window_start"]),
        "window_end": format_instant(row["window_end"]),
        "status": row["status"],
    })


def pickup_record(row):
    return _tail(row, {
        "id": row["id"],
        "room_block_commitment_id": row["room_block_commitment_id"],
        "night_date": format_date(row["night_date"]),
        "rooms_picked_up": row["rooms_picked_up"],
        "rate_charged_amount": money_out(row["rate_charged_amount"]),
        "room_night_revenue_amount": money_out(row["room_night_revenue_amount"]),
    }, versioned=False)


def board_report(row):
    return _tail(row, {
        "id": row["id"],
        "period_start": format_date(row["period_start"]),
        "period_end": format_date(row["period_end"]),
        "definite_opportunity_count": row["definite_opportunity_count"],
        "definite_room_nights": row["definite_room_nights"],
        "lost_opportunity_count": row["lost_opportunity_count"],
        "lost_room_nights_by_reason": dict(row["lost_room_nights_by_reason"]),
        "incentive_spend_committed_amount": money_out(row["incentive_spend_committed_amount"]),
        "lodging_tax_recognized_amount": money_out(row["lodging_tax_recognized_amount"]),
        "cost_per_definite_room_night": money_out(row["cost_per_definite_room_night"]),
        "attrition_recovered_amount": money_out(row["attrition_recovered_amount"]),
        "status": row["status"],
        "published_at": format_instant(row["published_at"]),
    })
