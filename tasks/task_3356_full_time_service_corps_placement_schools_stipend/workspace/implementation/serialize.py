"""Serializers: every declared entity field, computed fields derived on read."""
from decimal import Decimal

import services as svc


def _hours_float(d):
    return float(Decimal(d).quantize(Decimal("0.01")))


def site_json(s):
    out = {
        "id": s["id"],
        "name": s["name"],
        "city": s["city"],
        "service_year_start": s["service_year_start"],
        "service_year_end": s["service_year_end"],
        "annual_stipend_cents": s["annual_stipend_cents"],
        "district_committed_cents": s["district_committed_cents"],
        "philanthropy_committed_cents": s["philanthropy_committed_cents"],
        "federal_committed_cents": s["federal_committed_cents"],
        "district_received_cents": s["district_received_cents"],
        "philanthropy_received_cents": s["philanthropy_received_cents"],
        "federal_received_cents": s["federal_received_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
    out.update(svc.site_ledger(s))
    out.update(svc.site_cost_share(s))
    return out


def school_json(s):
    return {
        "id": s["id"],
        "site_id": s["site_id"],
        "name": s["name"],
        "district_name": s["district_name"],
        "team_size": s["team_size"],
        "service_scope": list(s["service_scope"]),
        "annual_cost_share_cents": s["annual_cost_share_cents"],
        "agreement_status": s["agreement_status"],
        "data_sharing_status": s["data_sharing_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def application_json(a):
    return {
        "id": a["id"],
        "site_id": a["site_id"],
        "full_name": a["full_name"],
        "date_of_birth": a["date_of_birth"],
        "education_level": a["education_level"],
        "citizenship_status": a["citizenship_status"],
        "prior_service_terms": a["prior_service_terms"],
        "prior_full_awards_received": a["prior_full_awards_received"],
        "status": a["status"],
        "rejection_reason": a["rejection_reason"],
        "enrolled_member_id": a["enrolled_member_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def member_json(m):
    v = svc.verified_hours(m)
    vf = svc.verified_fundraising_hours(m)
    projected, award_proj = svc.member_projection(m)
    return {
        "id": m["id"],
        "site_id": m["site_id"],
        "full_name": m["full_name"],
        "service_status": m["service_status"],
        "stipend_status": m["stipend_status"],
        "award_status": m["award_status"],
        "verified_hours_total": _hours_float(v),
        "verified_fundraising_hours": _hours_float(vf),
        "projected_hours_total": _hours_float(projected),
        "award_projected_cents": award_proj,
        "award_amount_cents": m["award_amount_cents"],
        "exit_type": m["exit_type"],
        "exit_date": m["exit_date"],
        "net_stipend_received_cents": svc.member_net_stipend(m),
        "active_assignment_count": svc.member_active_assignment_count(m),
        "active_caseload_count": svc.member_active_caseload_count(m),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def team_json(t):
    return {
        "id": t["id"],
        "school_id": t["school_id"],
        "name": t["name"],
        "team_size_snapshot": t["team_size_snapshot"],
        "min_active_members": svc.team_min_members(t),
        "backfill_limit": t["backfill_limit"],
        "backfill_deadline": t["backfill_deadline"],
        "backfill_count": svc.team_backfill_count(t),
        "active_assignment_count": svc.team_active_count(t),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def assignment_json(a):
    return {
        "id": a["id"],
        "team_id": a["team_id"],
        "corps_member_id": a["corps_member_id"],
        "role": a["role"],
        "start_date": a["start_date"],
        "end_date": a["end_date"],
        "is_backfill": a["is_backfill"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def student_json(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "external_student_ref": s["external_student_ref"],
        "grade_level": s["grade_level"],
        "focus_list_type": s["focus_list_type"],
        "baseline_attendance_pct": s["baseline_attendance_pct"],
        "current_attendance_pct": s["current_attendance_pct"],
        "enrollment_status": s["enrollment_status"],
        "caseload_status": s["caseload_status"],
        "assigned_member_id": s["assigned_member_id"],
        "assigned_start_date": s["assigned_start_date"],
        "assigned_end_date": s["assigned_end_date"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def hour_entry_json(e):
    # ServiceHourEntry carries only id + created_at (no updated_at / version).
    return {
        "id": e["id"],
        "corps_member_id": e["corps_member_id"],
        "service_date": e["service_date"],
        "hours": _hours_float(Decimal(str(e["hours"]))),
        "category": e["category"],
        "description": e["description"],
        "status": e["status"],
        "review_reason": e["review_reason"],
        "reviewed_by": e["reviewed_by"],
        "created_at": e["created_at"],
    }


def payment_json(p):
    return {
        "id": p["id"],
        "corps_member_id": p["corps_member_id"],
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "period_days": p["period_days"],
        "base_amount_cents": p["base_amount_cents"],
        "final_gross_cents": p["final_gross_cents"],
        "deduction_cents": p["deduction_cents"],
        "net_amount_cents": p["net_amount_cents"],
        "status": p["status"],
        "created_by": p["created_by"],
        "approved_by": p["approved_by"],
        "decision_reason": p["decision_reason"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def report_json(r):
    return {
        "id": r["id"],
        "school_id": r["school_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "eligible_student_count": r["eligible_student_count"],
        "improved_student_count": r["improved_student_count"],
        "pct_improved": r["pct_improved"],
        "status": r["status"],
        "return_reason": r["return_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
