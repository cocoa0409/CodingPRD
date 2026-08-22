"""Resource serialisers.

Every resource carries the four system-managed properties of PRD 2.6 —
`id`, `created_at`, `updated_at`, `version` — alongside its declared fields
(SCAFFOLD 1.1).  Datetimes render as ISO 8601 UTC with three fractional digits.
"""
from datetime import datetime

import db

COMMON = ("created_at", "updated_at", "version")

ELECTION_FIELDS = (
    "id", "title", "academic_year", "status", "current_round", "petition_deadline",
    "quiet_period_hours", "voting_opens_at", "voting_closes_at", "spending_cap_cents",
    "poster_cap", "quorum_pct", "runoff_threshold_pct", "eligible_voter_count",
    "ballots_cast_count", "turnout_pct", "runoff_required_office_count",
    "ballot_integrity_status", "certified_by_user_id", "certified_at",
) + COMMON

OFFICE_FIELDS = (
    "id", "election_id", "name", "seat_count", "eligible_class_years",
    "required_signature_count", "min_gpa", "min_credits", "required_training_modules",
    "term_start_date", "term_end_date", "status", "filled_seat_count",
    "valid_votes_count", "abstain_votes_count", "invalidated_votes_count",
) + COMMON

STUDENT_FIELDS = (
    "id", "full_name", "student_number", "class_year", "enrollment_status", "gpa",
    "credits_completed", "disciplinary_hold",
) + COMMON

CANDIDACY_FIELDS = (
    "id", "election_id", "office_id", "student_id", "slate_leader_candidacy_id",
    "statement", "status", "transition_status", "training_modules_completed",
    "ballot_position", "petition_signature_total_count", "petition_signature_valid_count",
    "petition_signature_ineligible_count", "petition_signature_pending_count",
    "petition_signature_rejected_count", "petition_signature_voided_count",
    "spending_reported_cents", "spending_committed_cents", "spending_reversed_cents",
    "spending_final_cents", "poster_count", "penalty_points_total",
    "slate_snapshot_member_ids", "raw_votes_count", "certified_votes_count",
    "provisional_share_pct", "certified_share_pct", "disqualified_reason",
    "term_start_date", "term_end_date", "activated_at",
) + COMMON

SIGNATURE_FIELDS = (
    "id", "candidacy_id", "signer_student_id", "signed_at", "status",
    "eligibility_result", "reject_reason", "verified_by_user_id",
) + COMMON

EXPENSE_FIELDS = (
    "id", "candidacy_id", "category", "amount_cents", "quantity", "shared_with_slate",
    "incurred_at", "venue_code", "event_starts_at", "event_ends_at", "status",
    "approved_by_user_id",
) + COMMON

CASE_FIELDS = (
    "id", "election_id", "candidacy_id", "rule_code", "severity", "description",
    "status", "penalty_points", "prior_upheld_count", "timing_factor_applied",
    "overspend_points_applied", "filed_by_user_id", "adjudicated_by_user_id",
    "upheld_at",
) + COMMON

REFERENDUM_FIELDS = (
    "id", "election_id", "title", "article_reference", "body_text",
    "approval_threshold_pct", "drafting_status", "outcome_status", "yes_votes_count",
    "no_votes_count", "abstain_votes_count", "approval_pct", "return_reason",
) + COMMON

BALLOT_FIELDS = (
    "id", "election_id", "round", "status", "line_count", "active_line_count",
    "locked_at", "published_at",
) + COMMON

BALLOT_LINE_FIELDS = (
    "id", "ballot_id", "office_id", "candidacy_id", "referendum_id", "line_type",
    "position", "status",
) + COMMON

VOTE_FIELDS = (
    "id", "election_id", "ballot_id", "student_id", "round", "selections", "status",
    "cast_at", "void_reason",
) + COMMON

APPEAL_FIELDS = (
    "id", "election_id", "candidacy_id", "compliance_case_id", "grounds",
    "remedy_requested", "status", "resolved_by_user_id", "resolution_note", "filed_at",
) + COMMON


def _value(val):
    if isinstance(val, datetime):
        return db.iso_millis(val)
    if isinstance(val, list):
        return [_value(item) for item in val]
    if isinstance(val, dict):
        return {k: _value(v) for k, v in val.items()}
    return val


def _shape(row, fields):
    return {name: _value(row.get(name)) for name in fields}


def election(row):
    return _shape(row, ELECTION_FIELDS)


def office(row):
    return _shape(row, OFFICE_FIELDS)


def student(row):
    return _shape(row, STUDENT_FIELDS)


def candidacy(row):
    return _shape(row, CANDIDACY_FIELDS)


def signature(row):
    return _shape(row, SIGNATURE_FIELDS)


def expense(row):
    return _shape(row, EXPENSE_FIELDS)


def case(row):
    return _shape(row, CASE_FIELDS)


def referendum(row):
    return _shape(row, REFERENDUM_FIELDS)


def ballot(row):
    return _shape(row, BALLOT_FIELDS)


def ballot_line(row):
    return _shape(row, BALLOT_LINE_FIELDS)


def vote(row):
    return _shape(row, VOTE_FIELDS)


def appeal(row):
    return _shape(row, APPEAL_FIELDS)
