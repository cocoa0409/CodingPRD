"""Entity serializers. Explicit field whitelists; internal keys (prefixed _)
and secrets (password) never leak."""
from services import ce_totals


def ser_candidate(c):
    return {
        "id": c["id"],
        "email": c["email"],
        "full_name": c["full_name"],
        "home_jurisdiction_code": c["home_jurisdiction_code"],
        "education_status": c["education_status"],
        "experience_status": c["experience_status"],
        "exam_status": c["exam_status"],
        "certificate_eligible": c["certificate_eligible"],
        "record_standing": c["record_standing"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_jurisdiction(j):
    return {
        "id": j["id"],
        "code": j["code"],
        "name": j["name"],
        "requires_supplemental_exam": j["requires_supplemental_exam"],
        "min_total_experience_hours": j["min_total_experience_hours"],
        "ce_hours_required": j["ce_hours_required"],
        "ce_hsw_hours_required": j["ce_hsw_hours_required"],
        "ce_carry_over_allowed": j["ce_carry_over_allowed"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_supervisor(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "license_number": s["license_number"],
        "jurisdiction_code": s["jurisdiction_code"],
        "license_status": s["license_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_evaluation(e):
    return {
        "id": e["id"],
        "candidate_id": e["candidate_id"],
        "path_type": e["path_type"],
        "institution_name": e["institution_name"],
        "semester_credit_hours": e["semester_credit_hours"],
        "status": e["status"],
        "deficiency_notes": e["deficiency_notes"],
        "review_count": e["review_count"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "candidate_id": r["candidate_id"],
        "supervisor_id": r["supervisor_id"],
        "practice_area": r["practice_area"],
        "hours": r["hours"],
        "work_period_start": r["work_period_start"],
        "work_period_end": r["work_period_end"],
        "work_setting": r["work_setting"],
        "status": r["status"],
        "submitted_at": r["submitted_at"],
        "credit_pct": r["credit_pct"],
        "credited_hours": r["credited_hours"],
        "return_reason": r["return_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_authorization(a):
    return {
        "id": a["id"],
        "candidate_id": a["candidate_id"],
        "jurisdiction_code": a["jurisdiction_code"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_division(d):
    return {
        "id": d["id"],
        "candidate_id": d["candidate_id"],
        "authorization_id": d["authorization_id"],
        "division_code": d["division_code"],
        "status": d["status"],
        "scheduled_date": d["scheduled_date"],
        "attempt_count": d["attempt_count"],
        "attempt_dates": list(d["attempt_dates"]),
        "last_failed_at": d["last_failed_at"],
        "passed_at": d["passed_at"],
        "expires_at": d["expires_at"],
        "result": d["result"],
        "scaled_score": d["scaled_score"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_supplemental(s):
    return {
        "id": s["id"],
        "candidate_id": s["candidate_id"],
        "jurisdiction_code": s["jurisdiction_code"],
        "exam_date": s["exam_date"],
        "status": s["status"],
        "result": s["result"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_certificate(c):
    hours, hsw, lifetime = ce_totals(c)
    return {
        "id": c["id"],
        "candidate_id": c["candidate_id"],
        "serial_number": c["serial_number"],
        "home_jurisdiction_code": c["home_jurisdiction_code"],
        "ce_hours_required": c["ce_hours_required"],
        "ce_hsw_hours_required": c["ce_hsw_hours_required"],
        "status": c["status"],
        "issued_at": c["issued_at"],
        "period_start": c["period_start"],
        "period_end": c["period_end"],
        "renewal_count": c["renewal_count"],
        "ce_hours_current_period": hours,
        "ce_hsw_current_period": hsw,
        "lifetime_ce_hours": lifetime,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_ce_entry(e):
    return {
        "id": e["id"],
        "certificate_id": e["certificate_id"],
        "hours": e["hours"],
        "hsw": e["hsw"],
        "completed_date": e["completed_date"],
        "provider": e["provider"],
        "voided": e["voided"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_transmittal(t):
    return {
        "id": t["id"],
        "certificate_id": t["certificate_id"],
        "jurisdiction_code": t["jurisdiction_code"],
        "status": t["status"],
        "denial_reason": t["denial_reason"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_disciplinary(r):
    return {
        "id": r["id"],
        "candidate_id": r["candidate_id"],
        "jurisdiction_code": r["jurisdiction_code"],
        "allegation": r["allegation"],
        "filed_by_user_id": r["filed_by_user_id"],
        "status": r["status"],
        "resolution_notes": r["resolution_notes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
