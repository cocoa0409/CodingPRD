"""Entity -> JSON projections."""
import clock
from money import num
from validate import dump_schedule


def _audit(row, out):
    out["created_at"] = clock.fmt_instant(row["created_at"])
    out["updated_at"] = clock.fmt_instant(row["updated_at"])
    out["version"] = row["version"]
    return out


def event(row):
    out = {
        "id": row["id"],
        "event_code": row["event_code"],
        "name": row["name"],
        "program_type": row["program_type"],
        "start_date": clock.fmt_date(row["start_date"]),
        "end_date": clock.fmt_date(row["end_date"]),
        "nights_span": row["nights_span"],
        "peak_attendees": row["peak_attendees"],
        "requested_room_nights": row["requested_room_nights"],
        "largest_meeting_space_sqft": row["largest_meeting_space_sqft"],
        "budget_ceiling_usd": num(row["budget_ceiling_usd"]),
        "preferred_program_only": row["preferred_program_only"],
        "status": row["status"],
        "sourcing_owner_user_id": row["sourcing_owner_user_id"],
        "shortlisted_venue_count": row["shortlisted_venue_count"],
        "best_total_cost_usd": num(row["best_total_cost_usd"]),
        "awarded_proposal_id": row["awarded_proposal_id"],
        "committed_spend_usd": num(row["committed_spend_usd"]),
        "cancellation_liability_usd": num(row["cancellation_liability_usd"]),
        "budget_remaining_usd": num(row["budget_remaining_usd"]),
        "savings_recognized_usd": num(row["savings_recognized_usd"]),
    }
    return _audit(row, out)


def benchmark(row):
    return {
        "id": row["id"],
        "destination_tier": row["destination_tier"],
        "program_type": row["program_type"],
        "benchmark_adr_usd": num(row["benchmark_adr_usd"]),
        "benchmark_service_charge_pct": num(row["benchmark_service_charge_pct"]),
        "benchmark_tax_pct": num(row["benchmark_tax_pct"]),
        "created_at": clock.fmt_instant(row["created_at"]),
    }


def venue(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "city": row["city"],
        "country": row["country"],
        "destination_tier": row["destination_tier"],
        "guest_rooms_total": row["guest_rooms_total"],
        "largest_space_sqft": row["largest_space_sqft"],
        "preferred_supplier_status": row["preferred_supplier_status"],
        "performance_score": num(row["performance_score"]),
        "performance_score_simple_mean": num(row["performance_score_simple_mean"]),
        "simple_mean_score": num(row["performance_score_simple_mean"]),
        "performance_review_count": row["performance_review_count"],
        "blocked_room_nights": row["blocked_room_nights"],
    }
    return _audit(row, out)


def entry(row):
    out = {
        "id": row["id"],
        "event_id": row["event_id"],
        "venue_id": row["venue_id"],
        "rank_seq": row["rank_seq"],
        "inspection_required": row["inspection_required"],
        "status": row["status"],
        "program_status_at_shortlist": row["program_status_at_shortlist"],
        "elimination_reason": row["elimination_reason"],
        "inspection_count": row["inspection_count"],
    }
    return _audit(row, out)


def inspection(row):
    out = {
        "id": row["id"],
        "shortlist_entry_id": row["shortlist_entry_id"],
        "venue_id": row["venue_id"],
        "inspector_user_id": row["inspector_user_id"],
        "window_start": clock.fmt_instant(row["window_start"]),
        "window_end": clock.fmt_instant(row["window_end"]),
        "travel_buffer_minutes": row["travel_buffer_minutes"],
        "occupied_until": clock.fmt_instant(row["occupied_until"]),
        "status": row["status"],
        "findings_score": row["findings_score"],
        "cancel_reason": row["cancel_reason"],
    }
    return _audit(row, out)


def rfp(row):
    out = {
        "id": row["id"],
        "event_id": row["event_id"],
        "round_number": row["round_number"],
        "previous_rfp_id": row["previous_rfp_id"],
        "response_due_at": clock.fmt_instant(row["response_due_at"]),
        "standard_response_version": row["standard_response_version"],
        "instructions": row["instructions"],
        "status": row["status"],
        "invited_count": row["invited_count"],
        "submitted_count": row["submitted_count"],
        "issued_at": clock.fmt_instant(row["issued_at"]),
        "closed_at": clock.fmt_instant(row["closed_at"]),
    }
    return _audit(row, out)


def proposal(row):
    out = {
        "id": row["id"],
        "rfp_id": row["rfp_id"],
        "venue_id": row["venue_id"],
        "status": row["status"],
        "room_rate_usd": num(row["room_rate_usd"]),
        "rate_type": row["rate_type"],
        "commission_pct": num(row["commission_pct"]),
        "room_nights_offered": row["room_nights_offered"],
        "comp_room_ratio": row["comp_room_ratio"],
        "resort_fee_usd_per_night": num(row["resort_fee_usd_per_night"]),
        "service_charge_pct": num(row["service_charge_pct"]),
        "tax_pct": num(row["tax_pct"]),
        "av_estimate_usd": num(row["av_estimate_usd"]),
        "fnb_minimum_usd": num(row["fnb_minimum_usd"]),
        "concession_credit_usd": num(row["concession_credit_usd"]),
        "attrition_allowance_pct": num(row["attrition_allowance_pct"]),
        "cancellation_schedule": dump_schedule(row["cancellation_schedule"]),
        "force_majeure_scope": row["force_majeure_scope"],
        "rebooking_credit_pct": num(row["rebooking_credit_pct"]),
        "net_adr_usd": num(row["net_adr_usd"]),
        "comp_room_nights": row["comp_room_nights"],
        "paid_room_nights": row["paid_room_nights"],
        "total_cost_contracted_usd": num(row["total_cost_contracted_usd"]),
        "total_cost_modeled_usd": num(row["total_cost_modeled_usd"]),
        "last_evaluation_basis": row["last_evaluation_basis"],
        "benchmark_variance_pct": num(row["benchmark_variance_pct"]),
        "compliance_status": row["compliance_status"],
        "negotiation_round_count": row["negotiation_round_count"],
        "submitted_at": clock.fmt_instant(row["submitted_at"]),
    }
    return _audit(row, out)


def evaluation(row):
    return {
        "id": row["id"],
        "proposal_id": row["proposal_id"],
        "basis": row["basis"],
        "evaluated_by_user_id": row["evaluated_by_user_id"],
        "paid_room_nights_used": row["paid_room_nights_used"],
        "room_revenue_usd": num(row["room_revenue_usd"]),
        "resort_fee_total_usd": num(row["resort_fee_total_usd"]),
        "av_adjusted_usd": num(row["av_adjusted_usd"]),
        "fnb_usd": num(row["fnb_usd"]),
        "service_charge_usd": num(row["service_charge_usd"]),
        "tax_usd": num(row["tax_usd"]),
        "concession_applied_usd": num(row["concession_applied_usd"]),
        "attrition_damages_usd": num(row["attrition_damages_usd"]),
        "total_cost_usd": num(row["total_cost_usd"]),
        "benchmark_adr_usd": num(row["benchmark_adr_usd"]),
        "evaluated_at": clock.fmt_instant(row["evaluated_at"]),
        "created_at": clock.fmt_instant(row["created_at"]),
    }


def counter(row):
    out = {
        "id": row["id"],
        "proposal_id": row["proposal_id"],
        "round_seq": row["round_seq"],
        "term_category": row["term_category"],
        "proposed_numeric_value": num(row["proposed_numeric_value"]),
        "proposed_text_value": row["proposed_text_value"],
        "planner_note": row["planner_note"],
        "initiated_by_user_id": row["initiated_by_user_id"],
        "resolution": row["resolution"],
        "resolved_at": clock.fmt_instant(row["resolved_at"]),
    }
    return _audit(row, out)


def contract(row):
    out = {
        "id": row["id"],
        "event_id": row["event_id"],
        "proposal_id": row["proposal_id"],
        "venue_id": row["venue_id"],
        "approval_state": row["approval_state"],
        "signature_state": row["signature_state"],
        "awarded_by_user_id": row["awarded_by_user_id"],
        "contracted_room_rate_usd": num(row["contracted_room_rate_usd"]),
        "contracted_paid_room_nights": row["contracted_paid_room_nights"],
        "contracted_room_revenue_usd": num(row["contracted_room_revenue_usd"]),
        "pre_rebate_total_usd": num(row["pre_rebate_total_usd"]),
        "volume_rebate_pct": num(row["volume_rebate_pct"]),
        "volume_rebate_usd": num(row["volume_rebate_usd"]),
        "contracted_total_usd": num(row["contracted_total_usd"]),
        "peak_rooms_per_night": row["peak_rooms_per_night"],
        "attrition_allowance_pct": num(row["attrition_allowance_pct"]),
        "cancellation_schedule": dump_schedule(row["cancellation_schedule"]),
        "force_majeure_scope": row["force_majeure_scope"],
        "rebooking_credit_pct": num(row["rebooking_credit_pct"]),
        "service_charge_pct": num(row["service_charge_pct"]),
        "tax_pct": num(row["tax_pct"]),
        "resort_fee_usd_per_night": num(row["resort_fee_usd_per_night"]),
        "fnb_minimum_usd": num(row["fnb_minimum_usd"]),
        "concession_applied_usd": num(row["concession_applied_usd"]),
        "deposit_total_usd": num(row["deposit_total_usd"]),
        "deposit_paid_usd": num(row["deposit_paid_usd"]),
        "deposit_outstanding_usd": num(row["deposit_outstanding_usd"]),
        "approval_step_count": row["approval_step_count"],
        "planner_signatory_name": row["planner_signatory_name"],
        "venue_signatory_name": row["venue_signatory_name"],
        "executed_at": clock.fmt_instant(row["executed_at"]),
        "terminated_at": clock.fmt_instant(row["terminated_at"]),
        "cancellation_fee_usd": num(row["cancellation_fee_usd"]),
        "rebooking_credit_usd": num(row["rebooking_credit_usd"]),
        "termination_reason": row["termination_reason"],
    }
    return _audit(row, out)


def step(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "step_seq": row["step_seq"],
        "approval_level": row["approval_level"],
        "required_role": row["required_role"],
        "decision": row["decision"],
        "approver_user_id": row["approver_user_id"],
        "decision_note": row["decision_note"],
        "decided_at": clock.fmt_instant(row["decided_at"]),
    }
    return _audit(row, out)


def installment(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "installment_seq": row["installment_seq"],
        "weight_pct": num(row["weight_pct"]),
        "amount_usd": num(row["amount_usd"]),
        "due_date": clock.fmt_date(row["due_date"]),
        "status": row["status"],
        "paid_amount_usd": num(row["paid_amount_usd"]),
        "paid_at": clock.fmt_instant(row["paid_at"]),
        "payment_reference": row["payment_reference"],
    }
    return _audit(row, out)


def report(row):
    out = {
        "id": row["id"],
        "event_id": row["event_id"],
        "contract_id": row["contract_id"],
        "actual_room_nights": row["actual_room_nights"],
        "actual_fnb_usd": num(row["actual_fnb_usd"]),
        "actual_av_usd": num(row["actual_av_usd"]),
        "attrition_allowed_nights": row["attrition_allowed_nights"],
        "attrition_shortfall_nights": row["attrition_shortfall_nights"],
        "attrition_charge_usd": num(row["attrition_charge_usd"]),
        "actual_room_cost_usd": num(row["actual_room_cost_usd"]),
        "realized_service_charge_usd": num(row["realized_service_charge_usd"]),
        "realized_tax_usd": num(row["realized_tax_usd"]),
        "realized_total_usd": num(row["realized_total_usd"]),
        "benchmark_room_cost_usd": num(row["benchmark_room_cost_usd"]),
        "savings_vs_benchmark_usd": num(row["savings_vs_benchmark_usd"]),
        "savings_vs_budget_usd": num(row["savings_vs_budget_usd"]),
        "notes": row["notes"],
    }
    return _audit(row, out)


def review(row):
    out = {
        "id": row["id"],
        "venue_id": row["venue_id"],
        "event_id": row["event_id"],
        "review_source": row["review_source"],
        "service_score": row["service_score"],
        "value_score": row["value_score"],
        "av_quality_score": row["av_quality_score"],
        "responsiveness_score": row["responsiveness_score"],
        "composite_score": num(row["composite_score"]),
        "reviewer_user_id": row["reviewer_user_id"],
        "comment": row["comment"],
    }
    return _audit(row, out)
