"""Serializers. Each spec entry is (field_name, kind) with kind in
raw / date / instant / num."""

from decimal import Decimal

import clock

CANDIDATE = [
    ("candidate_code", "raw"),
    ("full_name", "raw"),
    ("program_track", "raw"),
    ("home_grid_x", "raw"),
    ("home_grid_y", "raw"),
    ("readiness_score", "raw"),
    ("readiness_status", "raw"),
    ("readiness_variant_used", "raw"),
    ("licensure_status", "raw"),
    ("report_status", "raw"),
    ("recommended_by_user_id", "raw"),
    ("recommended_at", "instant"),
    ("denial_reason", "raw"),
    ("reported_by_user_id", "raw"),
    ("reported_at", "instant"),
    ("reporting_cycle", "raw"),
    ("state_report_deadline", "date"),
]

READINESS_ITEM = [
    ("candidate_id", "raw"),
    ("item_type", "raw"),
    ("status", "raw"),
    ("exam_score", "raw"),
    ("credits", "num"),
    ("clearance_scope", "raw"),
    ("issued_on", "date"),
    ("expires_on", "date"),
    ("verified_by_user_id", "raw"),
    ("verified_at", "instant"),
    ("rejection_note", "raw"),
]

DISTRICT = [
    ("name", "raw"),
    ("district_code", "raw"),
    ("state_code", "raw"),
    ("requires_district_fingerprint", "raw"),
    ("travel_reimbursement_enabled", "raw"),
]

AGREEMENT = [
    ("district_id", "raw"),
    ("term", "raw"),
    ("window_start", "date"),
    ("window_end", "date"),
    ("status", "raw"),
    ("placement_cap", "raw"),
    ("stipend_rate_cents_per_week", "raw"),
    ("allowed_subjects", "raw"),
    ("allowed_grade_bands", "raw"),
    ("seats_reserved", "raw"),
    ("seats_committed", "raw"),
    ("capacity_posture", "raw"),
    ("stipend_committed_cents", "raw"),
    ("suspension_reason", "raw"),
]

TEACHER = [
    ("district_id", "raw"),
    ("full_name", "raw"),
    ("site_name", "raw"),
    ("site_grid_x", "raw"),
    ("site_grid_y", "raw"),
    ("subject_endorsement", "raw"),
    ("grade_band", "raw"),
    ("years_experience", "raw"),
    ("consecutive_terms_hosted", "raw"),
    ("max_concurrent_candidates", "raw"),
    ("qualification_status", "raw"),
    ("training_completed_on", "date"),
    ("training_expires_on", "date"),
    ("active_placement_count", "raw"),
    ("disqualification_reason", "raw"),
]

SUPERVISOR = [
    ("full_name", "raw"),
    ("employment_type", "raw"),
    ("primary_subject", "raw"),
    ("covered_grade_bands", "raw"),
    ("home_grid_x", "raw"),
    ("home_grid_y", "raw"),
    ("max_travel_miles", "raw"),
    ("max_caseload_points_override", "raw"),
    ("max_caseload_points", "raw"),
    ("caseload_points", "raw"),
    ("accepting_new_placements", "raw"),
]

REQUEST = [
    ("candidate_id", "raw"),
    ("preferred_district_id", "raw"),
    ("term", "raw"),
    ("requested_subject", "raw"),
    ("requested_grade_band", "raw"),
    ("max_commute_miles", "raw"),
    ("term_start_date", "date"),
    ("weeks_scheduled", "raw"),
    ("term_end_date", "date"),
    ("status", "raw"),
    ("routing_round", "raw"),
    ("reroute_count", "raw"),
    ("excluded_cooperating_teacher_ids", "raw"),
    ("current_placement_id", "raw"),
]

PLACEMENT = [
    ("request_id", "raw"),
    ("candidate_id", "raw"),
    ("cooperating_teacher_id", "raw"),
    ("agreement_id", "raw"),
    ("supervisor_id", "raw"),
    ("replaces_placement_id", "raw"),
    ("subject", "raw"),
    ("grade_band", "raw"),
    ("start_date", "date"),
    ("end_date", "date"),
    ("weeks_scheduled", "raw"),
    ("commute_miles", "raw"),
    ("supervisor_points", "raw"),
    ("placement_status", "raw"),
    ("stipend_status", "raw"),
    ("stipend_variant", "raw"),
    ("stipend_weekly_cents", "raw"),
    ("weeks_credited", "raw"),
    ("stipend_gross_cents", "raw"),
    ("travel_reimbursement_cents", "raw"),
    ("observation_compliance_ratio", "num"),
    ("summative_completed_count", "raw"),
    ("removal_reason", "raw"),
    ("removal_requested_by_role", "raw"),
    ("removal_requested_by_user_id", "raw"),
    ("removal_decided_by_user_id", "raw"),
    ("removal_narrative", "raw"),
    ("voided_reason", "raw"),
    ("settlement_date", "date"),
    ("completed_at", "instant"),
]

CYCLE = [
    ("placement_id", "raw"),
    ("supervisor_id", "raw"),
    ("sequence_no", "raw"),
    ("cycle_type", "raw"),
    ("window_start", "instant"),
    ("window_end", "instant"),
    ("status", "raw"),
    ("observed_at", "instant"),
    ("rubric_score", "num"),
    ("reschedule_count", "raw"),
    ("resolution_note", "raw"),
]

ASSESSMENT = [
    ("placement_id", "raw"),
    ("window_opens_at", "instant"),
    ("window_closes_at", "instant"),
    ("status", "raw"),
    ("attempt_no", "raw"),
    ("artifact_reference", "raw"),
    ("submitted_at", "instant"),
    ("task_planning", "num"),
    ("task_instruction", "num"),
    ("task_assessment", "num"),
    ("task_professionalism", "num"),
    ("total_score", "raw"),
    ("scored_by_user_id", "raw"),
    ("scored_at", "instant"),
    ("returned_feedback", "raw"),
]


def _value(row, name, kind):
    value = row.get(name)
    if value is None:
        return None
    if kind == "date":
        return clock.fmt_date(value)
    if kind == "instant":
        return clock.fmt_instant(value)
    if kind == "num":
        return float(value) if isinstance(value, Decimal) else value
    if isinstance(value, list):
        return list(value)
    return value


def dump(row, spec):
    out = {"id": row["id"]}
    for name, kind in spec:
        out[name] = _value(row, name, kind)
    out["created_at"] = clock.fmt_instant(row["created_at"])
    out["updated_at"] = clock.fmt_instant(row["updated_at"])
    out["version"] = row["version"]
    return out


def dump_all(rows, spec):
    return [dump(row, spec) for row in rows]
