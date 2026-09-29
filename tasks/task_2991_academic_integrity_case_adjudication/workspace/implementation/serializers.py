"""JSON projections of every stored row.

Thirteen of the fifteen resource types carry id/created_at/updated_at/version.
EvidenceItem and PanelVote are immutable and carry only id and created_at --
their responses must not invent updated_at or version (PRD 2.5).
"""

import calc
from db import S
from util import fmt_dt, num


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def _immutable(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
    }


def department_json(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "name": row["name"],
        "enrolled_student_count": row["enrolled_student_count"],
        "faculty_headcount": row["faculty_headcount"],
        "open_case_count": calc.department_open_case_count(row),
        "training_completion_pct": num(calc.department_training_completion_pct(row)),
        "reporting_rate_per_1k_submitted": num(row["reporting_rate_per_1k_submitted"]),
        "monitoring_flag": row["monitoring_flag"],
    })
    return out


def faculty_json(row):
    status, completed_at, module_code = calc.faculty_training(row)
    out = _common(row)
    out.update({
        "department_id": row["department_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "training_status": status,
        "training_completed_at": fmt_dt(completed_at),
        "training_module_code": module_code,
        "reports_submitted_count": calc.faculty_reports_submitted_count(row),
    })
    return out


def student_json(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "program_code": row["program_code"],
        "class_year": row["class_year"],
        "prior_upheld_count": calc.student_prior_upheld_count(row["id"]),
        "active_sanction_points": calc.student_active_sanction_points(row["id"]),
        "standing": calc.student_standing(row["id"]),
        "transcript_notation": calc.student_transcript_notation(row["id"]),
    })
    return out


def offering_json(row):
    out = _common(row)
    out.update({
        "department_id": row["department_id"],
        "instructor_id": row["instructor_id"],
        "course_code": row["course_code"],
        "term_code": row["term_code"],
        "grade_components": [
            {
                "code": component["code"],
                "max_points": component["max_points"],
                "weight_pct": component["weight_pct"],
            }
            for component in row["grade_components"]
        ],
    })
    return out


def report_json(row):
    out = _common(row)
    out.update({
        "offering_id": row["offering_id"],
        "student_id": row["student_id"],
        "reporter_id": row["reporter_id"],
        "alleged_violation_type": row["alleged_violation_type"],
        "narrative": row["narrative"],
        "incident_at": fmt_dt(row["incident_at"]),
        "component_scores": [
            {"code": entry["code"], "earned_points": entry["earned_points"]}
            for entry in row["component_scores"]
        ],
        "submitted_at": fmt_dt(row["submitted_at"]),
        "status": row["status"],
        "evidence_strength_score": num(row["evidence_strength_score"]),
        "evidence_complete": calc.evidence_complete(row),
        "returned_at": fmt_dt(row["returned_at"]),
        "triaged_at": fmt_dt(row["triaged_at"]),
        "resubmission_count": row["resubmission_count"],
        "triage_note": row["triage_note"],
    })
    return out


def evidence_json(row):
    out = _immutable(row)
    out.update({
        "report_id": row["report_id"],
        "kind": row["kind"],
        "sha256": row["sha256"],
        "page_count": row["page_count"],
        "similarity_pct": num(row["similarity_pct"]),
    })
    return out


def case_json(row):
    out = _common(row)
    out.update({
        "report_id": row["report_id"],
        "student_id": row["student_id"],
        "offering_id": row["offering_id"],
        "case_number": row["case_number"],
        "origin": row["origin"],
        "pathway": row["pathway"],
        "adjudication_status": row["adjudication_status"],
        "notation_status": row["notation_status"],
        "responsibility_finding": row["responsibility_finding"],
        "finding_basis": row["finding_basis"],
        "hearing_round": row["hearing_round"],
        "overturned": row["overturned"],
        "decided_at": fmt_dt(row["decided_at"]),
        "evidence_strength_score": num(row["evidence_strength_score"]),
        "baseline_course_grade_pct": num(row["baseline_course_grade_pct"]),
        "cross_course_pattern_points": row["cross_course_pattern_points"],
        "prior_upheld_count_at_assessment": row["prior_upheld_count_at_assessment"],
        "prior_escalation_points": row["prior_escalation_points"],
        "provisional_severity_index": num(row["provisional_severity_index"]),
        "severity_index": num(row["severity_index"]),
        "recommended_ladder_rank": row["recommended_ladder_rank"],
        "informal_severity_index": num(row["informal_severity_index"]),
        "informal_recommended_ladder_rank": row["informal_recommended_ladder_rank"],
        "panel_severity_recommendation": row["panel_severity_recommendation"],
        "pre_appeal_adjudication_status": row["pre_appeal_adjudication_status"],
        "dismiss_reason": row["dismiss_reason"],
        "expungement_eligible_at": fmt_dt(row["expungement_eligible_at"]),
    })
    return out


def notification_json(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "kind": row["kind"],
        "response_window_days": row["response_window_days"],
        "sent_at": fmt_dt(row["sent_at"]),
        "response_deadline_at": fmt_dt(row["response_deadline_at"]),
        "acknowledged_at": fmt_dt(row["acknowledged_at"]),
    })
    return out


def engagement_json(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "advisor_full_name": row["advisor_full_name"],
        "advisor_kind": row["advisor_kind"],
        "advisor_bar_licensed": row["advisor_bar_licensed"],
        "status": row["status"],
        "speaking_rights": calc.speaking_rights(row),
        "reconfirmation_required": row["reconfirmation_required"],
        "decision_reason": row["decision_reason"],
    })
    return out


def meeting_json(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "instructor_id": row["instructor_id"],
        "start_at": fmt_dt(row["start_at"]),
        "end_at": fmt_dt(row["end_at"]),
        "duration_minutes": row["duration_minutes"],
        "status": row["status"],
        "advisor_present": row["advisor_present"],
    })
    return out


def room_json(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "seat_capacity": row["seat_capacity"],
        "buffer_minutes": row["buffer_minutes"],
        "sessions_per_day_cap": row["sessions_per_day_cap"],
        "booked_minutes_total": calc.room_booked_minutes(row),
    })
    return out


def session_json(row):
    effective, _finding, _recommendation = calc.panel_tally(row)
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "room_id": row["room_id"],
        "chair_id": row["chair_id"],
        "panelist_ids": list(row["panelist_ids"]),
        "required_panel_size": row["required_panel_size"],
        "start_at": fmt_dt(row["start_at"]),
        "end_at": fmt_dt(row["end_at"]),
        "status": row["status"],
        "round_number": row["round_number"],
        "effective_vote_count": effective,
        "quorum_required": row["quorum_required"],
        "panel_finding": row["panel_finding"],
        "panel_severity_recommendation": row["panel_severity_recommendation"],
        "adjourn_reason": row["adjourn_reason"],
    })
    return out


def vote_json(row):
    out = _immutable(row)
    out.update({
        "session_id": row["session_id"],
        "panelist_id": row["panelist_id"],
        "verdict": row["verdict"],
        "severity_recommendation": row["severity_recommendation"],
        "cast_at": fmt_dt(row["cast_at"]),
    })
    return out


def sanction_json(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "replaces_sanction_id": row["replaces_sanction_id"],
        "kind": row["kind"],
        "ladder_rank": row["ladder_rank"],
        "grade_component_code": row["grade_component_code"],
        "effective_from": fmt_dt(row["effective_from"]),
        "status": row["status"],
        "origin": row["origin"],
        "baseline_course_grade_pct": num(row["baseline_course_grade_pct"]),
        "adjusted_course_grade_pct": num(row["adjusted_course_grade_pct"]),
        "grade_penalty_delta_pct": num(row["grade_penalty_delta_pct"]),
        "imposed_at": fmt_dt(row["imposed_at"]),
        "completed_at": fmt_dt(row["completed_at"]),
        "vacated_reason": row["vacated_reason"],
    })
    return out


def appeal_json(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "grounds": row["grounds"],
        "statement": row["statement"],
        "filed_at": fmt_dt(row["filed_at"]),
        "status": row["status"],
        "hearing_round_at_filing": row["hearing_round_at_filing"],
        "reduced_ladder_rank": row["reduced_ladder_rank"],
        "decision_reason": row["decision_reason"],
        "decided_at": fmt_dt(row["decided_at"]),
    })
    return out
