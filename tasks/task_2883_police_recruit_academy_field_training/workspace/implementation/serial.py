"""Entity serialisers. Computed readings are derived at read time."""
from core import d2, fmt_date, fmt_instant, num, store
import calc


def _meta(row, versioned=True):
    out = {"created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def hours_map(mapping):
    return dict((key, num(d2(value))) for key, value in mapping.items())


def standard_json(row):
    out = {
        "id": row["id"],
        "code": row["code"],
        "state_code": row["state_code"],
        "min_total_hours": num(row["min_total_hours"]),
        "min_passing_score": num(row["min_passing_score"]),
        "max_remediation_attempts": row["max_remediation_attempts"],
        "max_absence_hours": num(row["max_absence_hours"]),
        "topic_requirements": [
            {
                "topic_code": entry["topic_code"],
                "required_hours": num(entry["required_hours"]),
                "exam_required": entry["exam_required"],
            }
            for entry in row["topic_requirements"]
        ],
        "fitness_event_floor_points": row["fitness_event_floor_points"],
        "fitness_pass_score": row["fitness_pass_score"],
    }
    out.update(_meta(row))
    return out


def class_json(row):
    out = {
        "id": row["id"],
        "certification_standard_id": row["certification_standard_id"],
        "class_code": row["class_code"],
        "start_date": fmt_date(row["start_date"]),
        "planned_seats": row["planned_seats"],
        "status": row["status"],
        "credited_topic_hours_total": num(calc.class_credited_topic_hours_total(row)),
        "unmet_topic_hours": hours_map(calc.class_unmet_topic_hours(row)),
        "projected_topic_hours": hours_map(calc.class_projected_topic_hours(row)),
        "graduated_count": calc.class_graduated_count(row),
    }
    out.update(_meta(row))
    return out


def recruit_json(row):
    out = {
        "id": row["id"],
        "academy_class_id": row["academy_class_id"],
        "applicant_number": row["applicant_number"],
        "full_name": row["full_name"],
        "date_of_birth": fmt_date(row["date_of_birth"]),
        "age_bracket": row["age_bracket"],
        "pipeline_stage": row["pipeline_stage"],
        "clearance_status": row["clearance_status"],
        "academy_status": row["academy_status"],
        "probation_status": row["probation_status"],
        "credited_hours_total": num(calc.recruit_total_hours(row, "ATTENDED")),
        "scheduled_basis_hours_total": num(calc.recruit_total_hours(row, "SCHEDULED")),
        "per_topic_credited_hours": hours_map(calc.recruit_per_topic_hours(row, "ATTENDED")),
        "unexcused_absence_hours": num(calc.recruit_unexcused_absence_hours(row)),
        "make_up_hours_owed": num(calc.recruit_make_up_hours_owed(row)),
        "remediation_attempts_used": calc.recruit_remediation_attempts_used(row),
        "probation_start": fmt_date(row["probation_start"]),
        "probation_base_days": row["probation_base_days"],
        "probation_extension_days": row["probation_extension_days"],
        "probation_milestone_due_date": fmt_date(row["probation_milestone_due_date"]),
        "probation_milestone_score": num(row["probation_milestone_score"]),
        "probation_scheduled_end": fmt_date(row["probation_scheduled_end"]),
        "dismissal_reason_code": row["dismissal_reason_code"],
    }
    out.update(_meta(row))
    return out


def screening_json(row):
    out = {
        "id": row["id"],
        "recruit_id": row["recruit_id"],
        "screening_type": row["screening_type"],
        "status": row["status"],
        "attempt_number": row["attempt_number"],
        "raw_metrics": _raw_metrics_json(row["raw_metrics"]),
        "composite_score": row["composite_score"],
        "disqualifier_codes": list(row["disqualifier_codes"]),
        "waiver_justification": row["waiver_justification"],
        "findings_recorded_by_user_id": row["findings_recorded_by_user_id"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "findings_recorded_at": row["findings_recorded_at"],
    }
    out.update(_meta(row))
    return out


def _raw_metrics_json(metrics):
    if metrics is None:
        return None
    return dict((key, num(value)) for key, value in metrics.items())


def instructor_json(row):
    out = {
        "id": row["id"],
        "badge_number": row["badge_number"],
        "full_name": row["full_name"],
        "certification_status": row["certification_status"],
        "certification_expires_at": fmt_instant(row["certification_expires_at"]),
        "authorized_topic_codes": list(row["authorized_topic_codes"]),
        "fto_certified": row["fto_certified"],
        "active_trainee_count": calc.instructor_active_trainee_count(row),
        "revocation_reason": row["revocation_reason"],
    }
    out.update(_meta(row))
    return out


def plan_json(row):
    out = {
        "id": row["id"],
        "instructor_id": row["instructor_id"],
        "topic_code": row["topic_code"],
        "title": row["title"],
        "contact_hours": num(row["contact_hours"]),
        "status": row["status"],
        "revision_number": row["revision_number"],
        "approved_revision_number": row["approved_revision_number"],
        "approved_at": fmt_instant(row["approved_at"]),
        "approved_by_user_id": row["approved_by_user_id"],
        "reviewer_notes": row["reviewer_notes"],
    }
    out.update(_meta(row))
    return out


def session_json(row):
    out = {
        "id": row["id"],
        "academy_class_id": row["academy_class_id"],
        "lesson_plan_id": row["lesson_plan_id"],
        "instructor_id": row["instructor_id"],
        "room_code": row["room_code"],
        "starts_at": fmt_instant(row["starts_at"]),
        "ends_at": fmt_instant(row["ends_at"]),
        "min_enrollment": row["min_enrollment"],
        "scheduled_hours": num(row["scheduled_hours"]),
        "topic_code": row["topic_code"],
        "pinned_lesson_plan_revision": row["pinned_lesson_plan_revision"],
        "status": row["status"],
        "enrolled_count": calc.session_enrolled_count(row),
        "credited_hours_total": num(calc.session_credited_hours_total(row)),
        "void_reason": row["void_reason"],
        "delivered_at": fmt_instant(row["delivered_at"]),
    }
    out.update(_meta(row))
    return out


def attendance_json(row):
    out = {
        "id": row["id"],
        "course_session_id": row["course_session_id"],
        "recruit_id": row["recruit_id"],
        "status": row["status"],
        "present_hours": num(row["present_hours"]),
        "ledger_status": row["ledger_status"],
        "credited_hours": num(row["credited_hours"]),
        "counted_absence_hours": num(row["counted_absence_hours"]),
        "void_reason": row["void_reason"],
    }
    out.update(_meta(row))
    return out


def exam_json(row):
    out = {
        "id": row["id"],
        "recruit_id": row["recruit_id"],
        "topic_code": row["topic_code"],
        "attempt_number": row["attempt_number"],
        "raw_score": num(row["raw_score"]),
        "passing_score": num(row["passing_score"]),
        "status": row["status"],
        "remediation_hours": num(row["remediation_hours"]),
        "graded_at": fmt_instant(row["graded_at"]),
        "graded_by_user_id": row["graded_by_user_id"],
    }
    out.update(_meta(row))
    return out


def rotation_json(row):
    terminal, rolling = calc.rotation_competency(row)
    out = {
        "id": row["id"],
        "recruit_id": row["recruit_id"],
        "fto_instructor_id": row["fto_instructor_id"],
        "prior_rotation_id": row["prior_rotation_id"],
        "phase_number": row["phase_number"],
        "start_date": fmt_date(row["start_date"]),
        "end_date": fmt_date(row["end_date"]),
        "status": row["status"],
        "dor_count": calc.rotation_dor_count(row),
        "remedial_flag_count": calc.rotation_remedial_flag_count(row),
        "competency_score": num(terminal),
        "rolling_mean_score": num(rolling),
        "final_narrative": row["final_narrative"],
        "abort_reason": row["abort_reason"],
    }
    out.update(_meta(row))
    return out


def report_json(row):
    out = {
        "id": row["id"],
        "field_training_rotation_id": row["field_training_rotation_id"],
        "author_instructor_id": row["author_instructor_id"],
        "observed_on": fmt_date(row["observed_on"]),
        "dimension_ratings": dict(row["dimension_ratings"]),
        "not_responding_to_training": row["not_responding_to_training"],
        "narrative": row["narrative"],
        "dor_mean": num(row["dor_mean"]),
        "voided": row["voided"],
    }
    out.update(_meta(row))
    return out


def entry_json(row):
    out = {
        "id": row["id"],
        "recruit_id": row["recruit_id"],
        "academy_class_id": row["academy_class_id"],
        "kind": row["kind"],
        "stage_code": row["stage_code"],
        "hours_delta": num(row["hours_delta"]),
        "topic_code": row["topic_code"],
        "actor_role": row["actor_role"],
        "actor_user_id": row["actor_user_id"],
        "subject_entity": row["subject_entity"],
        "subject_entity_id": row["subject_entity_id"],
        "detail": row["detail"],
        "recorded_at_utc": fmt_instant(row["recorded_at_utc"]),
    }
    out.update(_meta(row, versioned=False))
    return out
