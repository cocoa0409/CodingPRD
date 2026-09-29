"""Entity representations. Computed fields are derived on read from live state."""
import derive
from timeutil import fmt_date, fmt_instant


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": int(row["version"]),
    }


def payer(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "plan_type": row["plan_type"],
        "weekly_hour_cap": int(row["weekly_hour_cap"]),
        "evv_required": bool(row["evv_required"]),
        "billing_edit_ruleset": row["billing_edit_ruleset"],
        "appeal_window_days": int(row["appeal_window_days"]),
        "reduction_notice_days": int(row["reduction_notice_days"]),
    })
    return out


def patient(row):
    out = _common(row)
    out.update({
        "payer_id": row["payer_id"],
        "full_name": row["full_name"],
        "date_of_birth": fmt_date(row["date_of_birth"]),
        "primary_diagnosis": row["primary_diagnosis"],
        "requires_trach": bool(row["requires_trach"]),
        "requires_vent": bool(row["requires_vent"]),
        "requires_feeding_tube": bool(row["requires_feeding_tube"]),
        "parent_backup_available": bool(row["parent_backup_available"]),
        "status": row["status"],
    })
    return out


def plan(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "requested_hours_per_week": int(row["requested_hours_per_week"]),
        "start_date": fmt_date(row["start_date"]),
        "end_date": fmt_date(row["end_date"]),
        "ordering_physician_npi": row["ordering_physician_npi"],
        "status": row["status"],
        "revision_round": int(row["revision_round"]),
    })
    return out


def authorization(row):
    committed, remaining = derive.auth_week_hours(row)
    out = _common(row)
    out.update({
        "plan_of_care_id": row["plan_of_care_id"],
        "payer_id": row["payer_id"],
        "supersedes_authorization_id": row["supersedes_authorization_id"],
        "approved_hours_per_week": derive.hours2(row["approved_hours_per_week"]),
        "noticed_hours_per_week": (
            None if row["noticed_hours_per_week"] is None
            else derive.hours2(row["noticed_hours_per_week"])
        ),
        "reduction_effective_at": fmt_instant(row["reduction_effective_at"]),
        "effective_start": fmt_instant(row["effective_start"]),
        "effective_end": fmt_instant(row["effective_end"]),
        "status": row["status"],
        "renewal_chain_depth": int(row["renewal_chain_depth"]),
        "hours_committed_this_week": committed,
        "hours_remaining_this_week": remaining,
    })
    return out


def nurse(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "license_type": row["license_type"],
        "license_number": row["license_number"],
        "license_expires_on": fmt_date(row["license_expires_on"]),
        "max_weekly_hours": int(row["max_weekly_hours"]),
        "status": row["status"],
        "scheduled_minutes_this_week": derive.nurse_scheduled_minutes_this_week(row["id"]),
        "verified_skills": derive.verified_skills(row["id"]),
    })
    return out


def competency(row):
    out = _common(row)
    out.update({
        "nurse_id": row["nurse_id"],
        "skill": row["skill"],
        "validated_by_user_id": row["validated_by_user_id"],
        "validated_on": fmt_date(row["validated_on"]),
        "expires_on": fmt_date(row["expires_on"]),
        "status": row["status"],
        "revoked_reason": row["revoked_reason"],
    })
    return out


def case(row):
    fill_rate, unfilled = derive.case_fill_metrics(row)
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "authorization_id": row["authorization_id"],
        "continuity_nurse_id": row["continuity_nurse_id"],
        "assigned_supervisor_user_id": row["assigned_supervisor_user_id"],
        "concurrent_nurse_limit": int(row["concurrent_nurse_limit"]),
        "excluded_nurse_ids": list(row["excluded_nurse_ids"]),
        "status": row["status"],
        "hold_reason": row["hold_reason"],
        "hold_incident_report_id": row["hold_incident_report_id"],
        "unfilled_shift_count": unfilled,
        "fill_rate": fill_rate,
        "billed_units_to_date": derive.case_billed_units(row),
        "next_supervisory_visit_due_at": fmt_instant(derive.supervisory_due_at(row)),
        "supervisory_status": derive.supervisory_status(row),
    })
    return out


def shift(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "start_at": fmt_instant(row["start_at"]),
        "end_at": fmt_instant(row["end_at"]),
        "required_skills": list(row["required_skills"]),
        "scheduled_minutes": int(row["scheduled_minutes"]),
        "staffing_status": row["staffing_status"],
        "evv_status": row["evv_status"],
        "escalation_tier": row["escalation_tier"],
        "escalated_at": fmt_instant(row["escalated_at"]),
        "cancel_reason": row["cancel_reason"],
    })
    return out


def assignment(row):
    out = _common(row)
    out.update({
        "shift_id": row["shift_id"],
        "nurse_id": row["nurse_id"],
        "status": row["status"],
        "continuity_match": bool(row["continuity_match"]),
        "match_score_at_assignment": int(row["match_score_at_assignment"]),
        "cancel_reason": row["cancel_reason"],
    })
    return out


def timesheet(row):
    out = _common(row)
    out.update({
        "shift_assignment_id": row["shift_assignment_id"],
        "clock_in_at": fmt_instant(row["clock_in_at"]),
        "clock_out_at": fmt_instant(row["clock_out_at"]),
        "evv_method": row["evv_method"],
        "geo_verified": bool(row["geo_verified"]),
        "gross_billable_units": int(row["gross_billable_units"]),
        "edit_deduction_units": int(row["edit_deduction_units"]),
        "net_billable_units": int(row["net_billable_units"]),
        "edit_codes": list(row["edit_codes"]),
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "edit_reason": row["edit_reason"],
        "submitted_by_user_id": row["submitted_by_user_id"],
    })
    return out


def visit(row):
    """SupervisoryVisit is immutable: only id and created_at, no updated_at, no version."""
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "case_id": row["case_id"],
        "supervisor_user_id": row["supervisor_user_id"],
        "visit_at": fmt_instant(row["visit_at"]),
        "outcome": row["outcome"],
        "notes": row["notes"],
        "cadence_days_applied": int(row["cadence_days_applied"]),
        "next_due_at": fmt_instant(row["next_due_at"]),
    }


def incident(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "reported_by_user_id": row["reported_by_user_id"],
        "category": row["category"],
        "severity": row["severity"],
        "occurred_at": fmt_instant(row["occurred_at"]),
        "narrative": row["narrative"],
        "status": row["status"],
        "triggered_case_hold": bool(row["triggered_case_hold"]),
        "resolution": row["resolution"],
        "patient_returned_home": bool(row["patient_returned_home"]),
    })
    return out


def dispute(row):
    out = _common(row)
    out.update({
        "authorization_id": row["authorization_id"],
        "dispute_type": row["dispute_type"],
        "requested_hours_per_week": derive.hours2(row["requested_hours_per_week"]),
        "reason": row["reason"],
        "filed_by_user_id": row["filed_by_user_id"],
        "filed_at": fmt_instant(row["filed_at"]),
        "status": row["status"],
        "decided_hours_per_week": (
            None if row["decided_hours_per_week"] is None
            else derive.hours2(row["decided_hours_per_week"])
        ),
        "decided_at": fmt_instant(row["decided_at"]),
        "reviewer_user_id": row["reviewer_user_id"],
    })
    return out
