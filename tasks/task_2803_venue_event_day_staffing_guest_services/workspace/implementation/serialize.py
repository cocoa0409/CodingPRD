"""Per-entity JSON projections.

Field order follows SCAFFOLD.yaml's entity declarations; timestamps go through
core.fmt_dt so every instant carries exactly three fractional digits.
"""

from decimal import Decimal

from core import db, fmt_dt, now
import calc


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def event_json(row):
    out = {
        "name": row["name"],
        "event_date": fmt_dt(row["event_date"]),
        "doors_open_at": fmt_dt(row["doors_open_at"]),
        "doors_close_at": fmt_dt(row["doors_close_at"]),
        "expected_attendance": row["expected_attendance"],
        "historical_actual_attendance": row["historical_actual_attendance"],
        "attendance_tier": row["attendance_tier"],
        "refund_budget_total_cents": row["refund_budget_total_cents"],
        "refund_approved_total_cents": row["refund_approved_total_cents"],
        "refund_budget_remaining_cents": row["refund_budget_remaining_cents"],
        "gratuity_pool_cents": row["gratuity_pool_cents"],
        "gratuity_allocated_cents": row["gratuity_allocated_cents"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def position_type_json(row):
    out = {
        "code": row["code"],
        "display_name": row["display_name"],
        "base_hourly_rate_cents": row["base_hourly_rate_cents"],
        "attendance_ratio_per_1000": _num(row["attendance_ratio_per_1000"]),
        "min_headcount": row["min_headcount"],
        "required_certifications": list(row["required_certifications"]),
        "is_tip_eligible": row["is_tip_eligible"],
        "is_contracted_position": row["is_contracted_position"],
    }
    out.update(_common(row))
    return out


def staffing_plan_json(row):
    out = {
        "event_id": row["event_id"],
        "plan_variant": row["plan_variant"],
        "revision_number": row["revision_number"],
        "status": row["status"],
        "basis_attendance": row["basis_attendance"],
        "basis_attendance_tier": row["basis_attendance_tier"],
        "total_required_headcount": row["total_required_headcount"],
        "base_labor_cost_cents": row["base_labor_cost_cents"],
        "accessibility_surcharge_cents": row["accessibility_surcharge_cents"],
        "projected_labor_cost_cents": row["projected_labor_cost_cents"],
        "activated_at": fmt_dt(row["activated_at"]),
    }
    out.update(_common(row))
    return out


def position_slot_json(row):
    out = {
        "plan_id": row["plan_id"],
        "position_type_id": row["position_type_id"],
        "zone_code": row["zone_code"],
        "shift_start": fmt_dt(row["shift_start"]),
        "shift_end": fmt_dt(row["shift_end"]),
        "required_headcount_override": row["required_headcount_override"],
        "ratio_derived_headcount": row["ratio_derived_headcount"],
        "required_headcount": row["required_headcount"],
        "filled_headcount": row["filled_headcount"],
        "shift_minutes": row["shift_minutes"],
        "slot_labor_cost_cents": row["slot_labor_cost_cents"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def staff_member_json(row):
    out = {
        "full_name": row["full_name"],
        "employment_type": row["employment_type"],
        "seniority_date": fmt_dt(row["seniority_date"]),
        "hourly_rate_cents": row["hourly_rate_cents"],
        "in_backfill_pool": row["in_backfill_pool"],
        "status": row["status"],
        "reliability_score": row["reliability_score"],
        "season_reliability_score": row["season_reliability_score"],
        "no_show_strikes": row["no_show_strikes"],
        "completed_assignment_count": row["completed_assignment_count"],
        "last_status_reason": row["last_status_reason"],
    }
    out.update(_common(row))
    return out


def cert_status(row):
    """Never stored as sent: revoked wins, then the logical clock, then VALID."""
    if row["revoked_at"] is not None:
        return "REVOKED"
    if now() > row["expires_on"]:
        return "EXPIRED"
    return "VALID"


def certification_json(row):
    out = {
        "staff_member_id": row["staff_member_id"],
        "cert_type": row["cert_type"],
        "issued_on": fmt_dt(row["issued_on"]),
        "expires_on": fmt_dt(row["expires_on"]),
        "revoked_at": fmt_dt(row["revoked_at"]),
        "status": cert_status(row),
    }
    out.update(_common(row))
    return out


def shift_bid_json(row):
    out = {
        "staff_member_id": row["staff_member_id"],
        "position_slot_id": row["position_slot_id"],
        "submitted_at": fmt_dt(row["submitted_at"]),
        "rank_score": row["rank_score"],
        "decision_reason": row["decision_reason"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def staff_assignment_json(row):
    out = {
        "position_slot_id": row["position_slot_id"],
        "staff_member_id": row["staff_member_id"],
        "shift_bid_id": row["shift_bid_id"],
        "source": row["source"],
        "attendance_status": row["attendance_status"],
        "payout_status": row["payout_status"],
        "check_in_at": fmt_dt(row["check_in_at"]),
        "checked_out_at": fmt_dt(row["checked_out_at"]),
        "late_check_in": row["late_check_in"],
        "worked_minutes": row["worked_minutes"],
        "base_pay_cents": row["base_pay_cents"],
        "gratuity_cents": row["gratuity_cents"],
        "total_payout_cents": row["total_payout_cents"],
    }
    out.update(_common(row))
    return out


def backfill_request_json(row):
    out = {
        "position_slot_id": row["position_slot_id"],
        "triggering_assignment_id": row["triggering_assignment_id"],
        "filled_assignment_id": row["filled_assignment_id"],
        "selected_staff_member_id": row["selected_staff_member_id"],
        "attempt_count": row["attempt_count"],
        "cancel_reason": row["cancel_reason"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def issue_sla_breached(row):
    """resolved_at freezes the flag; otherwise the live logical clock decides."""
    reference = row["resolved_at"] if row["resolved_at"] is not None else now()
    return reference > row["sla_deadline"]


def guest_issue_json(row):
    out = {
        "event_id": row["event_id"],
        "escalated_from_issue_id": row["escalated_from_issue_id"],
        "assigned_staff_member_id": row["assigned_staff_member_id"],
        "channel": row["channel"],
        "category": row["category"],
        "severity": row["severity"],
        "description": row["description"],
        "seat_reference": row["seat_reference"],
        "relocation_zone_code": row["relocation_zone_code"],
        "reported_by_user_id": row["reported_by_user_id"],
        "resolved_by_user_id": row["resolved_by_user_id"],
        "resolution_type": row["resolution_type"],
        "sla_minutes": row["sla_minutes"],
        "sla_clock_started_at": fmt_dt(row["sla_clock_started_at"]),
        "sla_deadline": fmt_dt(row["sla_deadline"]),
        "sla_breached": issue_sla_breached(row),
        "resolved_at": fmt_dt(row["resolved_at"]),
        "reopen_count": row["reopen_count"],
        "refund_requested_cents": row["refund_requested_cents"],
        "refund_approved_cents": row["refund_approved_cents"],
        "refund_status": row["refund_status"],
        "refund_requested_by_user_id": row["refund_requested_by_user_id"],
        "refund_decided_by_user_id": row["refund_decided_by_user_id"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def accessibility_resource_json(row):
    out = {
        "event_id": row["event_id"],
        "resource_type": row["resource_type"],
        "zone_code": row["zone_code"],
        "unit_count": row["unit_count"],
        "peak_committed_units": row["peak_committed_units"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def accessibility_request_json(row):
    out = {
        "resource_id": row["resource_id"],
        "guest_reference": row["guest_reference"],
        "window_start": fmt_dt(row["window_start"]),
        "window_end": fmt_dt(row["window_end"]),
        "units_requested": row["units_requested"],
        "companion_seats_requested": row["companion_seats_requested"],
        "confirmed_at": fmt_dt(row["confirmed_at"]),
        "service_started_at": fmt_dt(row["service_started_at"]),
        "completed_at": fmt_dt(row["completed_at"]),
        "denial_reason": row["denial_reason"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def satisfaction_response_json(row):
    # The single append-only resource: id and created_at only, no version.
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "zone_code": row["zone_code"],
        "score": row["score"],
        "comment": row["comment"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "created_at": fmt_dt(row["created_at"]),
    }


SERIALIZERS = {
    "events": event_json,
    "position_types": position_type_json,
    "staffing_plans": staffing_plan_json,
    "position_slots": position_slot_json,
    "staff_members": staff_member_json,
    "certifications": certification_json,
    "shift_bids": shift_bid_json,
    "staff_assignments": staff_assignment_json,
    "backfill_requests": backfill_request_json,
    "guest_issues": guest_issue_json,
    "accessibility_resources": accessibility_resource_json,
    "accessibility_requests": accessibility_request_json,
    "satisfaction_responses": satisfaction_response_json,
}
