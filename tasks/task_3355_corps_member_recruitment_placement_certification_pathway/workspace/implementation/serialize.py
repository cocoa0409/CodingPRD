"""Entity serialization. Derived fields are recomputed on read so the response
always reflects the current logical clock, without writing the row."""

import calc
from store import SCHOOLS

COMMON_TAIL = ("created_at", "updated_at", "version")


def _pick(record, fields):
    out = {}
    for field in fields:
        out[field] = record.get(field)
    for field in COMMON_TAIL:
        out[field] = record.get(field)
    return out


def region(record):
    return _pick(
        record,
        [
            "id",
            "region_code",
            "name",
            "state_code",
            "term_start_date",
            "base_placement_fee_cents",
            "max_corps_members",
        ],
    )


def district(record, projection=None):
    out = _pick(
        record,
        [
            "id",
            "region_id",
            "name",
            "agreement_status",
            "hiring_commitment_slots",
            "placement_fee_per_member_cents",
            "unfilled_slot_penalty_cents",
            "fee_budget_cents",
            "committed_placement_count",
            "invoice_amount_cents",
        ],
    )
    if projection == "FORWARD_LOOKING":
        out["invoice_amount_cents"] = calc.district_forward_looking_invoice_cents(record)
    return out


def school(record):
    out = _pick(
        record,
        [
            "id",
            "district_id",
            "name",
            "grade_band",
            "subject_needs",
            "classroom_capacity",
            "occupied_classrooms",
        ],
    )
    out["occupied_classrooms"] = calc.school_occupied_classrooms(record)
    return out


def applicant(record):
    return _pick(
        record,
        [
            "id",
            "full_name",
            "email",
            "campus_name",
            "campus_tier",
            "graduation_year",
            "leadership_score",
            "achievement_score",
            "gpa",
        ],
    )


def application(record):
    return _pick(
        record,
        [
            "id",
            "applicant_id",
            "preferred_region_id",
            "subject_area",
            "grade_preference",
            "status",
            "verified_gpa",
            "revision_count",
            "selection_score",
            "final_selection_score",
            "decision_reason",
            "reviewed_by_user_id",
            "decided_by_user_id",
            "offer_expires_at",
            "created_corps_member_id",
            "returned_at",
        ],
    )


def pathway(record):
    return _pick(
        record,
        [
            "id",
            "region_id",
            "state_code",
            "certification_track",
            "required_coursework_hours",
            "required_practice_hours",
            "deadline_days_before_term",
            "coursework_fee_cents",
        ],
    )


def member(record):
    return _pick(
        record,
        [
            "id",
            "application_id",
            "cohort_year",
            "institute_status",
            "service_status",
            "practice_teaching_hours",
            "coursework_hours_completed",
            "certification_hours_verified",
            "readiness_score",
            "institute_stipend_cents",
            "service_started_at",
            "leave_started_at",
            "exit_reason",
        ],
    )


def placement(record):
    return _pick(
        record,
        [
            "id",
            "corps_member_id",
            "school_id",
            "subject_area",
            "grade_band",
            "status",
            "term_start_date",
            "term_end_date",
            "confirmed_at",
            "activated_at",
            "early_exit_reason",
            "employment_eligible",
            "placement_fee_cents",
        ],
    )


def milestone(record):
    out = _pick(
        record,
        [
            "id",
            "corps_member_id",
            "pathway_id",
            "milestone_type",
            "required_hours",
            "due_date",
            "progress_status",
            "verification_status",
            "completed_at",
            "completed_by_user_id",
            "verified_by_user_id",
            "deadline_status",
            "days_remaining",
        ],
    )
    days_remaining, band = calc.deadline_band(record)
    out["days_remaining"] = days_remaining
    out["deadline_status"] = band
    return out


def support_record(record):
    return _pick(
        record,
        [
            "id",
            "corps_member_id",
            "record_type",
            "coach_user_id",
            "session_start",
            "session_end",
            "effectiveness_score",
            "notes",
        ],
    )


def school_or_none(school_id):
    return SCHOOLS.get(school_id)
