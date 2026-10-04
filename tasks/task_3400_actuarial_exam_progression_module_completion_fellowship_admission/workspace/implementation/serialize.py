"""Serializers for all seventeen resource types (PRD §2.5 common fields).
Computed fields (credit totals, seats_held, waitlist_count, attendance_booked,
scaled_score, projected_result, modules_passed_count, completion_pct) are
recomputed fresh on every read; internal keys (``_seq``) never leak.
"""

import services as S
from store import fmt_clock


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _dt(value):
    return fmt_clock(value) if value is not None else None


def candidate(c):
    earned, transfer, total = S.credit_totals(c["id"])
    out = {
        "email": c["email"],
        "full_name": c["full_name"],
        "membership_tier": c["membership_tier"],
        "status": c["status"],
        "suspended_until": _dt(c["suspended_until"]),
        "associate_admitted_at": _dt(c["associate_admitted_at"]),
        "fellow_admitted_at": _dt(c["fellow_admitted_at"]),
        "earned_exam_credit_hours": earned,
        "transfer_credit_hours": transfer,
        "total_credit_hours": total,
        "last_evaluated_at": _dt(c["last_evaluated_at"]),
    }
    out.update(_common(c))
    return out


def syllabus(v):
    out = {
        "version_code": v["version_code"],
        "status": v["status"],
        "credit_map": dict(v["credit_map"] or {}),
        "activated_at": _dt(v["activated_at"]),
    }
    out.update(_common(v))
    return out


def exam(e):
    out = {
        "exam_code": e["exam_code"],
        "title": e["title"],
        "credit_hours": e["credit_hours"],
        "is_prelim": e["is_prelim"],
        "prerequisite_exam_id": e["prerequisite_exam_id"],
        "syllabus_version_id": e["syllabus_version_id"],
        "status": e["status"],
    }
    out.update(_common(e))
    return out


def exam_window(w):
    out = {
        "exam_id": w["exam_id"],
        "window_code": w["window_code"],
        "registration_opens_at": _dt(w["registration_opens_at"]),
        "registration_deadline": _dt(w["registration_deadline"]),
        "testing_starts_at": _dt(w["testing_starts_at"]),
        "testing_ends_at": _dt(w["testing_ends_at"]),
        "capacity": w["capacity"],
        "base_fee_cents": w["base_fee_cents"],
        "late_surcharge_cents": w["late_surcharge_cents"],
        "status": w["status"],
        "seats_held": S.seats_held(w),
        "waitlist_count": S.waitlist_count(w),
    }
    out.update(_common(w))
    return out


def registration(r):
    scaled = S.scaled_score_of(r)
    out = {
        "candidate_id": r["candidate_id"],
        "exam_window_id": r["exam_window_id"],
        "logistics_status": r["logistics_status"],
        "grading_status": r["grading_status"],
        "raw_score": r["raw_score"],
        "scaled_score": float(scaled) if scaled is not None else None,
        "result": r["result"],
        "projected_result": S.projected_result_of(r),
        "fee_charged_cents": r["fee_charged_cents"],
        "refund_cents": r["refund_cents"],
        "cancel_reason": r["cancel_reason"],
        "sat_at": _dt(r["sat_at"]),
    }
    out.update(_common(r))
    return out


def pass_mark(s):
    out = {
        "exam_window_id": s["exam_window_id"],
        "proposed_mark": s["proposed_mark"],
        "ratified_mark": s["ratified_mark"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def vee_submission(s):
    out = {
        "candidate_id": s["candidate_id"],
        "topic": s["topic"],
        "university": s["university"],
        "course_title": s["course_title"],
        "grade_points": s["grade_points"],
        "status": s["status"],
        "reviewer_note": s["reviewer_note"],
        "reviewed_at": _dt(s["reviewed_at"]),
    }
    out.update(_common(s))
    return out


def track_enrollment(t):
    stats = S.enrollment_stats(t)
    out = {
        "candidate_id": t["candidate_id"],
        "track_code": t["track_code"],
        "status": t["status"],
        "modules_passed_count": stats["modules_passed_count"],
        "completion_pct": stats["completion_pct"],
    }
    out.update(_common(t))
    return out


def module(m):
    out = {
        "module_code": m["module_code"],
        "track_code": m["track_code"],
        "sequence_index": m["sequence_index"],
        "title": m["title"],
        "is_capstone": m["is_capstone"],
        "passing_score": m["passing_score"],
        "cooldown_days": m["cooldown_days"],
    }
    out.update(_common(m))
    return out


def module_attempt(a):
    out = {
        "track_enrollment_id": a["track_enrollment_id"],
        "module_id": a["module_id"],
        "attempt_number": a["attempt_number"],
        "status": a["status"],
        "score": a["score"],
        "submitted_at": _dt(a["submitted_at"]),
    }
    out.update(_common(a))
    return out


def project_assessment(p):
    out = {
        "candidate_id": p["candidate_id"],
        "track_enrollment_id": p["track_enrollment_id"],
        "title": p["title"],
        "status": p["status"],
        "grader_ids": list(p["grader_ids"]),
        "scores": list(p["scores"]),
        "final_score": p["final_score"],
        "result": p["result"],
    }
    out.update(_common(p))
    return out


def course_session(s):
    out = {
        "session_code": s["session_code"],
        "starts_at": _dt(s["starts_at"]),
        "ends_at": _dt(s["ends_at"]),
        "capacity": s["capacity"],
        "status": s["status"],
        "attendance_booked": S.attendance_booked(s),
    }
    out.update(_common(s))
    return out


def course_attendance(a):
    out = {
        "course_session_id": a["course_session_id"],
        "candidate_id": a["candidate_id"],
        "status": a["status"],
        "verified_at": _dt(a["verified_at"]),
        "verified_by": a["verified_by"],
    }
    out.update(_common(a))
    return out


def transfer_credit_request(t):
    out = {
        "candidate_id": t["candidate_id"],
        "source_body": t["source_body"],
        "claimed_hours": t["claimed_hours"],
        "agreement_class": t["agreement_class"],
        "granted_hours": t["granted_hours"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def cpd_attestation(a):
    out = {
        "candidate_id": a["candidate_id"],
        "cycle_year": a["cycle_year"],
        "attested_hours": a["attested_hours"],
        "carryover_hours": a["carryover_hours"],
        "required_hours": a["required_hours"],
        "verified_hours": a["verified_hours"],
        "status": a["status"],
        "verified_at": _dt(a["verified_at"]),
    }
    out.update(_common(a))
    return out


def discipline_case(d):
    out = {
        "candidate_id": d["candidate_id"],
        "charge": d["charge"],
        "severity": d["severity"],
        "status": d["status"],
        "resolution": d["resolution"],
        "suspension_days": d["suspension_days"],
        "suspended_until": _dt(d["suspended_until"]),
        "resolved_at": _dt(d["resolved_at"]),
    }
    out.update(_common(d))
    return out


def credential_application(a):
    out = {
        "candidate_id": a["candidate_id"],
        "credential": a["credential"],
        "status": a["status"],
        "deficiency_codes": list(a["deficiency_codes"]),
        "evaluated_at": _dt(a["evaluated_at"]),
    }
    out.update(_common(a))
    return out
