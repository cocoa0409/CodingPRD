"""Entity shape assertions and domain invariant checkers."""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    GOOD_MIN,
    PROBATION_MIN,
    REQUIRED_MEMBER_COUNT,
    REQUIRED_ROLE_SLOTS,
)


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_club(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("club_name"), str) and data["club_name"]
    assert data.get("club_type") in ("COMMUNITY", "CORPORATE", "CAMPUS", "ADVANCED")
    assert data.get("charter_status") in ("ORGANIZING", "CHARTERED", "SUSPENDED", "REVOKED")
    assert data.get("good_standing") in ("GOOD", "PROBATION", "NOT_IN_GOOD_STANDING")
    assert data.get("coaching_status") in ("NONE", "FLAGGED", "ASSIGNED", "COACHED")
    assert data.get("dcp_tier") in (
        "PRESIDENT_DISTINGUISHED",
        "SELECT_DISTINGUISHED",
        "DISTINGUISHED",
        "NONE",
    )
    assert isinstance(data.get("club_dues_cents"), int)
    assert isinstance(data.get("dues_cycle_index"), int) and data["dues_cycle_index"] >= 0
    for counter in (
        "good_standing_score",
        "paid_member_count",
        "total_member_count",
        "new_member_count_this_cycle",
        "officer_trained_count",
        "meetings_held_this_cycle",
        "approved_level_completions_this_cycle",
        "contest_participation_count",
        "dcp_recognition_points",
    ):
        assert isinstance(data.get(counter), int), f"{counter} must be an integer"
    assert_iso_or_null(data, "cycle_opened_at")
    assert_iso_or_null(data, "cycle_closed_at")
    assert_iso_or_null(data, "charter_date")


def assert_member(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("total_speeches_delivered"), int)
    assert isinstance(data.get("highest_level_completed"), int)


def assert_membership(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert is_valid_uuid(data.get("club_id", "")), "club_id must be a valid UUID"
    assert data.get("status") in ("PENDING", "ACTIVE", "LAPSED")
    assert data.get("dues_status") in ("ISSUED", "PAID", "OVERDUE", "VOID")
    assert isinstance(data.get("first_time_member"), bool)
    assert isinstance(data.get("dues_paid_through_cycle"), int)
    assert isinstance(data.get("consecutive_cycles_paid"), int)
    assert data.get("officer_role") in (
        "NONE",
        "PRESIDENT",
        "VP_EDUCATION",
        "VP_MEMBERSHIP",
        "VP_PUBLIC_RELATIONS",
        "SECRETARY",
        "TREASURER",
        "SERGEANT_AT_ARMS",
    )
    assert isinstance(data.get("speeches_delivered_this_cycle"), int)
    assert isinstance(data.get("roles_completed_this_cycle"), int)
    assert_iso_or_null(data, "join_date")


def assert_education_path(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be a valid UUID"
    assert data.get("path_code") in (
        "DYNAMIC_LEADERSHIP",
        "ENGAGING_HUMOR",
        "PERSUASIVE_INFLUENCE",
        "PRESENTATION_MASTERY",
        "TEAM_COLLABORATION",
        "VISIONARY_COMMUNICATION",
    )
    assert data.get("level") in ("LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5", "COMPLETED")
    assert data.get("status") in ("ACTIVE", "SUSPENDED")
    assert isinstance(data.get("approved_speeches_at_level"), int)
    assert isinstance(data.get("approved_projects_at_level"), int)
    assert_iso_or_null(data, "last_advanced_at")


def assert_project_completion(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("path_id", "")), "path_id must be a valid UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert is_valid_uuid(data.get("club_id", "")), "club_id must be a valid UUID"
    assert data.get("project_kind") in ("SPEECH", "EVALUATION", "LEADERSHIP")
    assert isinstance(data.get("level"), int) and 1 <= data["level"] <= 5
    assert data.get("status") in ("LOGGED", "EVALUATED", "APPROVED", "RETURNED")
    assert isinstance(data.get("counts_for_level_advancement"), bool)


def assert_meeting(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("club_id", "")), "club_id must be a valid UUID"
    assert data.get("status") in ("SCHEDULED", "HELD", "CANCELLED")
    assert data.get("required_role_slots") == REQUIRED_ROLE_SLOTS
    assert isinstance(data.get("filled_role_slots"), int)
    assert isinstance(data.get("quorum_met"), bool)
    assert_iso_or_null(data, "held_at")


def assert_role_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("meeting_id", "")), "meeting_id must be a valid UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert data.get("role_code") in (
        "TOASTMASTER",
        "TABLE_TOPICS_MASTER",
        "SPEAKER",
        "EVALUATOR",
        "TIMER",
        "AH_COUNTER",
        "GRAMMARIAN",
        "GENERAL_EVALUATOR",
    )
    assert data.get("role_class") in ("SPEECH", "FUNCTIONARY")
    assert data.get("status") in ("ASSIGNED", "COMPLETED", "NO_SHOW", "RELEASED")
    assert isinstance(data.get("credit_awarded"), bool)


def assert_officer_term(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("club_id", "")), "club_id must be a valid UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert data.get("office") in (
        "PRESIDENT",
        "VP_EDUCATION",
        "VP_MEMBERSHIP",
        "VP_PUBLIC_RELATIONS",
        "SECRETARY",
        "TREASURER",
        "SERGEANT_AT_ARMS",
    )
    assert data.get("status") in ("NOMINATED", "ELECTED", "TRAINED", "COMPLETED", "VACATED")
    assert isinstance(data.get("term_index"), int)


def assert_contest(data: dict):
    assert_common_fields(data)
    assert data.get("contest_level") in ("CLUB", "AREA", "DIVISION", "DISTRICT")
    assert data.get("contest_type") in (
        "INTERNATIONAL_SPEECH",
        "TALL_TALES",
        "EVALUATION",
        "HUMOROUS",
    )
    assert data.get("status") in ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
    assert isinstance(data.get("entry_count"), int)
    assert isinstance(data.get("judged_entry_count"), int)
    assert_iso_or_null(data, "completed_at")


def assert_contest_entry(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contest_id", "")), "contest_id must be a valid UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert is_valid_uuid(data.get("club_id", "")), "club_id must be a valid UUID"
    assert data.get("status") in ("ENTERED", "JUDGED", "ADVANCED", "ELIMINATED", "DISQUALIFIED")
    assert isinstance(data.get("ballot_count"), int)
    assert isinstance(data.get("judge_score_total"), int)


def assert_area_visit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("club_id", "")), "club_id must be a valid UUID"
    assert is_valid_uuid(data.get("director_member_id", "")), "director_member_id must be a valid UUID"
    assert data.get("visit_kind") in ("AREA_DIRECTOR", "DIVISION_DIRECTOR", "CLUB_COACH")
    assert data.get("status") in ("SCHEDULED", "COMPLETED", "MISSED")
    assert_iso_or_null(data, "completed_at")


def assert_iso_or_null(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or an ISO 8601 timestamp, got {value!r}"
    )


# ----------------------------------------------------------------------
# Instant comparisons
# ----------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp; the fractional-digit rendering is not significant."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str, field: str = "timestamp"):
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected the instant {expected}, got {actual}"
    )


def assert_instant_offset(actual: str, origin: str, field: str = "timestamp", **offset):
    expected = parse_instant(origin) + timedelta(**offset)
    assert parse_instant(actual) == expected, (
        f"{field}: expected {expected.isoformat()}, got {actual}"
    )


def assert_within_window(actual: str, start: str, end: str, field: str = "timestamp"):
    moment = parse_instant(actual)
    assert parse_instant(start) <= moment <= parse_instant(end), (
        f"{field}: {actual} is outside [{start}, {end}]"
    )


# ----------------------------------------------------------------------
# Domain invariants
# ----------------------------------------------------------------------

def assert_score_in_range(data: dict):
    assert 0 <= data["good_standing_score"] <= 100, (
        f"good_standing_score out of range: {data['good_standing_score']}"
    )


def assert_score_matches_posture(data: dict):
    """The posture bands of PRD §2.7 applied to the reported score."""
    score = data["good_standing_score"]
    standing = data["good_standing"]
    if score >= GOOD_MIN:
        expected = "GOOD"
    elif score >= PROBATION_MIN:
        expected = "PROBATION"
    else:
        expected = "NOT_IN_GOOD_STANDING"
    assert standing == expected, (
        f"score {score} should place the club in {expected}, got {standing}"
    )


def assert_paid_roster_invariant(club: dict, memberships: list):
    """paid_member_count == count(dues_paid_through_cycle >= dues_cycle_index)."""
    expected = sum(
        1 for ms in memberships if ms["dues_paid_through_cycle"] >= club["dues_cycle_index"]
    )
    assert club["paid_member_count"] == expected, (
        f"paid_member_count {club['paid_member_count']} != {expected} "
        f"at dues_cycle_index {club['dues_cycle_index']}"
    )


def assert_charter_minimum_reached(club: dict):
    assert club["paid_member_count"] >= REQUIRED_MEMBER_COUNT, (
        f"paid_member_count {club['paid_member_count']} below the charter minimum"
    )
