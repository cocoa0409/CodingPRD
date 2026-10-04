"""Entity serialisation.

Each entity renders exactly the fields declared in SCAFFOLD.yaml section 1.1
plus the four system-managed properties every resource carries: id, created_at,
updated_at and version (PRD section 2.4).  Internal bookkeeping keys (prefixed
with an underscore) are never exposed.
"""

from datetime import datetime

from db import iso

COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "club": [
        "club_name",
        "club_type",
        "corporate_sponsor_name",
        "district_number",
        "division_code",
        "area_code",
        "venue_name",
        "club_dues_cents",
        "sponsor_club_id",
        "organizing_meeting_at",
        "organizing_meeting_attendees",
        "charter_status",
        "charter_date",
        "good_standing",
        "good_standing_score",
        "cycle_open_standing",
        "dues_cycle_index",
        "cycle_opened_at",
        "cycle_closed_at",
        "paid_member_count",
        "total_member_count",
        "new_member_count_this_cycle",
        "officer_trained_count",
        "meetings_held_this_cycle",
        "approved_level_completions_this_cycle",
        "contest_participation_count",
        "dcp_recognition_points",
        "dcp_tier",
        "coaching_status",
    ],
    "member": [
        "full_name",
        "email",
        "home_area_code",
        "member_since",
        "total_speeches_delivered",
        "highest_level_completed",
    ],
    "membership": [
        "member_id",
        "club_id",
        "status",
        "dues_status",
        "join_date",
        "first_time_member",
        "dues_paid_through_cycle",
        "consecutive_cycles_paid",
        "quoted_total_cents",
        "officer_role",
        "speeches_delivered_this_cycle",
        "roles_completed_this_cycle",
    ],
    "education_path": [
        "membership_id",
        "path_code",
        "level",
        "status",
        "approved_speeches_at_level",
        "approved_projects_at_level",
        "level_started_at",
        "last_advanced_at",
    ],
    "project_completion": [
        "path_id",
        "member_id",
        "club_id",
        "project_code",
        "project_kind",
        "level",
        "speech_minutes",
        "delivered_at",
        "evaluator_member_id",
        "evaluation_summary",
        "status",
        "return_reason",
        "counts_for_level_advancement",
    ],
    "meeting": [
        "club_id",
        "scheduled_at",
        "duration_minutes",
        "venue_name",
        "theme",
        "status",
        "attendance_count",
        "quorum_met",
        "filled_role_slots",
        "required_role_slots",
        "held_at",
    ],
    "role_assignment": [
        "meeting_id",
        "member_id",
        "role_code",
        "role_class",
        "status",
        "credit_awarded",
        "released_reason",
    ],
    "officer_term": [
        "club_id",
        "member_id",
        "office",
        "term_index",
        "status",
        "nominated_at",
        "elected_at",
        "training_due_at",
        "trained_at",
    ],
    "contest": [
        "club_id",
        "contest_level",
        "contest_type",
        "district_number",
        "division_code",
        "area_code",
        "scheduled_at",
        "status",
        "entry_count",
        "judged_entry_count",
        "winner_entry_id",
        "completed_at",
    ],
    "contest_entry": [
        "contest_id",
        "member_id",
        "club_id",
        "speech_title",
        "status",
        "ballot_count",
        "judge_score_total",
        "placement",
    ],
    "area_visit": [
        "club_id",
        "director_member_id",
        "visit_kind",
        "scheduled_at",
        "status",
        "completed_at",
        "findings",
    ],
}


def render(kind, row):
    """One entity as a JSON-ready dict."""
    out = {}
    for field in COMMON:
        value = row.get(field)
        out[field] = iso(value) if isinstance(value, datetime) else value
    for field in FIELDS[kind]:
        value = row.get(field)
        out[field] = iso(value) if isinstance(value, datetime) else value
    return out


def render_all(kind, rows):
    return [render(kind, row) for row in rows]
