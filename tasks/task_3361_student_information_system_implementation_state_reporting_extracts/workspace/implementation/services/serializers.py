"""Entity -> API response dict serializers (internal fields stripped)."""
from dates import fmt_dt

_COMMON = ("created_at", "updated_at", "version")


def district_out(d):
    return {
        "id": d["id"], "name": d["name"], "state_code": d["state_code"],
        "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def year_out(y):
    return {
        "id": y["id"], "district_id": y["district_id"], "label": y["label"],
        "start_date": fmt_dt(y["start_date"]), "end_date": fmt_dt(y["end_date"]),
        "instructional_days": y["instructional_days"],
        "count_date": fmt_dt(y["count_date"]), "status": y["status"],
        "created_at": y["created_at"], "updated_at": y["updated_at"],
        "version": y["version"],
    }


def spec_out(s):
    return {
        "id": s["id"], "state_code": s["state_code"],
        "funding_method": s["funding_method"],
        "attendance_code_map": s["attendance_code_map"],
        "discipline_code_map": s["discipline_code_map"],
        "program_code_map": s["program_code_map"],
        "submission_window_opens_at": fmt_dt(s["submission_window_opens_at"]),
        "submission_window_closes_at": fmt_dt(s["submission_window_closes_at"]),
        "chronic_absence_threshold": s["chronic_absence_threshold"],
        "auto_withdraw_streak": s["auto_withdraw_streak"],
        "min_membership_days": s["min_membership_days"],
        "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def student_out(s):
    return {
        "id": s["id"], "district_id": s["district_id"],
        "student_number": s["student_number"], "first_name": s["first_name"],
        "last_name": s["last_name"], "birth_date": fmt_dt(s["birth_date"]),
        "entry_grade_level": s["entry_grade_level"], "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def course_out(c):
    return {
        "id": c["id"], "district_id": c["district_id"],
        "course_code": c["course_code"], "title": c["title"],
        "credit_hours": c["credit_hours"], "grade_band": c["grade_band"],
        "state_course_code": c["state_course_code"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def section_out(s):
    return {
        "id": s["id"], "course_id": s["course_id"],
        "school_year_id": s["school_year_id"], "teacher_ref": s["teacher_ref"],
        "term_label": s["term_label"], "room": s["room"],
        "period_start_min": s["period_start_min"],
        "period_end_min": s["period_end_min"], "capacity": s["capacity"],
        "roster_count": s["roster_count"], "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def enrollment_out(e):
    return {
        "id": e["id"], "student_id": e["student_id"],
        "school_year_id": e["school_year_id"], "grade_level": e["grade_level"],
        "program_code": e["program_code"],
        "state_program_code": e["state_program_code"],
        "program_weight": e["program_weight"],
        "entry_date": fmt_dt(e["entry_date"]),
        "exit_date": fmt_dt(e["exit_date"]),
        "prior_segment_days": e["prior_segment_days"],
        "membership_days": e["membership_days"],
        "absence_weight_sum": float(e["absence_weight_sum"]),
        "absence_rate": float(e["absence_rate"]),
        "fte_adm": float(e["fte_adm"]),
        "fte_count_date": float(e["fte_count_date"]),
        "lifecycle": e["lifecycle"], "absence_posture": e["absence_posture"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def event_out(ev):
    # AttendanceEvent is an immutable ledger entry: id and created_at only,
    # no updated_at / version.
    return {
        "id": ev["id"], "enrollment_id": ev["enrollment_id"],
        "attendance_date": fmt_dt(ev["attendance_date"]),
        "raw_code": ev["raw_code"],
        "state_attendance_code": ev["state_attendance_code"],
        "absence_weight": ev["absence_weight"],
        "is_excused": ev["is_excused"],
        "created_at": ev["created_at"],
    }


def incident_out(i):
    return {
        "id": i["id"], "student_id": i["student_id"],
        "enrollment_id": i["enrollment_id"],
        "incident_date": fmt_dt(i["incident_date"]),
        "raw_offense_code": i["raw_offense_code"],
        "action_type": i["action_type"], "action_days": i["action_days"],
        "state_offense_code": i["state_offense_code"],
        "severity_base": i["severity_base"],
        "severity_score": i["severity_score"], "status": i["status"],
        "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"],
    }


def extract_out(x):
    return {
        "id": x["id"], "school_year_id": x["school_year_id"],
        "collection_spec_id": x["collection_spec_id"],
        "generation": x["generation"], "status": x["status"],
        "record_count": x["record_count"],
        "invalid_record_count": x["invalid_record_count"],
        "total_fte_millis": x["total_fte_millis"],
        "chronic_absentee_count": x["chronic_absentee_count"],
        "escalation_priority": x["escalation_priority"],
        "supersedes_extract_id": x["supersedes_extract_id"],
        "submitted_at": fmt_dt(x["submitted_at"]),
        "created_at": x["created_at"], "updated_at": x["updated_at"],
        "version": x["version"],
    }


def portal_out(p):
    return {
        "id": p["id"], "student_id": p["student_id"],
        "account_type": p["account_type"], "access_level": p["access_level"],
        "grade_visibility": p["grade_visibility"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def feed_out(f):
    return {
        "id": f["id"], "district_id": f["district_id"],
        "platform": f["platform"], "status": f["status"],
        "last_synced_roster_count": f["last_synced_roster_count"],
        "last_synced_at": fmt_dt(f["last_synced_at"]),
        "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"],
    }


def run_out(r):
    return {
        "id": r["id"], "district_id": r["district_id"],
        "source_school_year_id": r["source_school_year_id"],
        "target_school_year_id": r["target_school_year_id"],
        "status": r["status"],
        "promoted_count": r["promoted_count"],
        "graduated_count": r["graduated_count"],
        "archived_student_count": r["archived_student_count"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }
