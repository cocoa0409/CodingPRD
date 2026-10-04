"""Entity serializers: record -> public JSON dict (computed fields included)."""

from derived import (
    total_enrollment,
    dues_current,
    brand_compliant,
    directory_visible,
    annual_dues_cents,
    latest_audit_verdict,
    compliant_classroom_count,
    ce_totals,
)


def serialize_catalog(c):
    return {
        "id": c["id"],
        "version_label": c["version_label"],
        "status": c["status"],
        "effective_from": c["effective_from"],
        "min_uninterrupted_work_minutes_by_level": c["min_uninterrupted_work_minutes_by_level"],
        "max_students_per_adult_by_level": c["max_students_per_adult_by_level"],
        "materials_pass_threshold": c["materials_pass_threshold"],
        "min_multi_age_span_years_by_level": c["min_multi_age_span_years_by_level"],
        "practicum_min_hours_by_level": c["practicum_min_hours_by_level"],
        "ce_hours_required": c["ce_hours_required"],
        "credential_validity_months": c["credential_validity_months"],
        "renewal_window_months": c["renewal_window_months"],
        "renewal_grace_months": c["renewal_grace_months"],
        "min_membership_months_before_accreditation": c["min_membership_months_before_accreditation"],
        "consultant_travel_buffer_days": c["consultant_travel_buffer_days"],
        "plan_response_days": c["plan_response_days"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_school(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "display_name": s["display_name"],
        "uses_method_name": s["uses_method_name"],
        "descriptor": s.get("descriptor"),
        "contact_email": s["contact_email"],
        "membership_level": s["membership_level"],
        "standing": s["standing"],
        "affiliated_since": s.get("affiliated_since"),
        "member_since": s.get("member_since"),
        "accredited_since": s.get("accredited_since"),
        "dues_paid_through": s.get("dues_paid_through"),
        "pinned_catalog_id": s.get("pinned_catalog_id"),
        "dues_current": dues_current(s),
        "brand_compliant": brand_compliant(s),
        "directory_visible": directory_visible(s),
        "total_enrollment": total_enrollment(s["id"]),
        "compliant_classroom_count": compliant_classroom_count(s["id"]),
        "annual_dues_cents": annual_dues_cents(s),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_classroom(c):
    return {
        "id": c["id"],
        "school_id": c["school_id"],
        "name": c["name"],
        "age_level": c["age_level"],
        "declared_age_span_years": c["declared_age_span_years"],
        "enrolled_student_count": c["enrolled_student_count"],
        "assistant_count": c["assistant_count"],
        "lead_credential_id": c.get("lead_credential_id"),
        "compliance_override": c["compliance_override"],
        "latest_audit_verdict": latest_audit_verdict(c["id"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_audit(a):
    return {
        "id": a["id"],
        "classroom_id": a["classroom_id"],
        "visit_id": a.get("visit_id"),
        "catalog_id": a["catalog_id"],
        "auditor_consultant_id": a["auditor_consultant_id"],
        "observed_at": a["observed_at"],
        "students_present": a["students_present"],
        "adults_present": a["adults_present"],
        "observed_uninterrupted_minutes": a["observed_uninterrupted_minutes"],
        "materials_groups": a["materials_groups"],
        "ratio_students_per_adult": a["ratio_students_per_adult"],
        "ratio_pass": a["ratio_pass"],
        "work_period_pass": a["work_period_pass"],
        "materials_score": a["materials_score"],
        "materials_pass": a["materials_pass"],
        "multi_age_pass": a["multi_age_pass"],
        "verdict": a["verdict"],
        "failed_checks": a["failed_checks"],
        "created_at": a["created_at"],
    }


def serialize_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "age_levels_offered": p["age_levels_offered"],
        "course_contact_hours_by_level": p["course_contact_hours_by_level"],
        "practicum_hours_by_level": p["practicum_hours_by_level"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_learner(l):
    return {
        "id": l["id"],
        "program_id": l["program_id"],
        "full_name": l["full_name"],
        "age_level": l["age_level"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_placement(p):
    return {
        "id": p["id"],
        "learner_id": p["learner_id"],
        "host_school_id": p["host_school_id"],
        "supervisor_credential_id": p.get("supervisor_credential_id"),
        "age_level": p["age_level"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "target_hours": p["target_hours"],
        "hours_logged": p["hours_logged"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_credential(c):
    cycle, rolling = ce_totals(c)
    return {
        "id": c["id"],
        "learner_id": c["learner_id"],
        "age_level": c["age_level"],
        "status": c["status"],
        "issued_at": c["issued_at"],
        "cycle_start": c["cycle_start"],
        "expires_at": c["expires_at"],
        "renewed_count": c["renewed_count"],
        "ce_hours_cycle_credited": float(cycle),
        "ce_hours_rolling_credited": float(rolling),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_application(a):
    return {
        "id": a["id"],
        "school_id": a["school_id"],
        "type": a["type"],
        "status": a["status"],
        "supporting_self_study_id": a.get("supporting_self_study_id"),
        "submitted_at": a.get("submitted_at"),
        "decided_at": a.get("decided_at"),
        "reviewer_user_id": a.get("reviewer_user_id"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_self_study(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "narrative": s["narrative"],
        "status": s["status"],
        "pinned_catalog_id": s["pinned_catalog_id"],
        "pinned_catalog_label": s["pinned_catalog_label"],
        "submitted_at": s.get("submitted_at"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_visit(v):
    return {
        "id": v["id"],
        "school_id": v["school_id"],
        "self_study_id": v["self_study_id"],
        "consultant_id": v["consultant_id"],
        "window_start": v["window_start"],
        "window_end": v["window_end"],
        "status": v["status"],
        "verdict": v.get("verdict"),
        "findings": v.get("findings") or [],
        "report_filed_at": v.get("report_filed_at"),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "school_id": p["school_id"],
        "visit_id": p.get("visit_id"),
        "required_actions": p["required_actions"],
        "due_date": p["due_date"],
        "status": p["status"],
        "response_notes": p.get("response_notes"),
        "submitted_at": p.get("submitted_at"),
        "verified_at": p.get("verified_at"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_pd_event(e):
    return {
        "id": e["id"],
        "title": e["title"],
        "provider_name": e["provider_name"],
        "start_at": e["start_at"],
        "end_at": e["end_at"],
        "ce_hours": e["ce_hours"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_ce_entry(e):
    return {
        "id": e["id"],
        "credential_id": e["credential_id"],
        "pd_event_id": e["pd_event_id"],
        "hours": e["hours"],
        "earned_at": e["earned_at"],
        "status": e["status"],
        "created_at": e["created_at"],
    }
