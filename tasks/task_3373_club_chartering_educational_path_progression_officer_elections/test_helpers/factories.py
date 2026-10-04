"""Payload factories — input fields only, PRD-exact field names."""
from typing import Any, Dict, List, Optional

from .constants import (
    CONTEST_AT,
    CYCLE_OPENED_AT,
    DEFAULT_MEETING_MINUTES,
    JOIN_DATE,
    MEETING_AT,
    ORGANIZING_MEETING_AT,
    ORGANIZING_MEETING_ATTENDEES,
    TEST_AREA_CODE,
    TEST_CLUB_DUES_CENTS,
    TEST_CLUB_NAME,
    TEST_DISTRICT_NUMBER,
    TEST_DIVISION_CODE,
    TEST_VENUE_NAME,
    VISIT_AT,
)


def create_club_payload(**overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/clubs."""
    payload: Dict[str, Any] = {
        "club_name": TEST_CLUB_NAME,
        "club_type": "COMMUNITY",
        "district_number": TEST_DISTRICT_NUMBER,
        "division_code": TEST_DIVISION_CODE,
        "area_code": TEST_AREA_CODE,
        "venue_name": TEST_VENUE_NAME,
        "club_dues_cents": TEST_CLUB_DUES_CENTS,
        "cycle_opened_at": CYCLE_OPENED_AT,
        "organizing_meeting_at": ORGANIZING_MEETING_AT,
        "organizing_meeting_attendees": ORGANIZING_MEETING_ATTENDEES,
    }
    payload.update(overrides)
    return payload


def create_membership_payload(**overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/memberships."""
    payload: Dict[str, Any] = {
        "full_name": "Ada Lovelace",
        "email": "ada@example.org",
        "join_date": JOIN_DATE,
        "first_time_member": True,
    }
    payload.update(overrides)
    return payload


def bulk_members_payload(club_id: str, members: List[Dict[str, Any]], pay_dues_immediately: bool = True):
    """Payload for POST /toastmasters/memberships/bulk."""
    return {
        "club_id": club_id,
        "members": members,
        "pay_dues_immediately": pay_dues_immediately,
    }


def numbered_members(count: int, prefix: str = "m", start: int = 1) -> List[Dict[str, Any]]:
    """`count` distinct member rows with well-formed emails, numbered from `start`."""
    return [
        {"full_name": f"{prefix}{index}", "email": f"{prefix}{index}@example.org"}
        for index in range(start, start + count)
    ]


def education_path_payload(membership_id: str, expected_membership_version: int, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/education-paths."""
    payload: Dict[str, Any] = {
        "membership_id": membership_id,
        "path_code": "DYNAMIC_LEADERSHIP",
        "expected_membership_version": expected_membership_version,
    }
    payload.update(overrides)
    return payload


def project_completion_payload(path_id: str, expected_education_path_version: int, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/project-completions."""
    payload: Dict[str, Any] = {
        "path_id": path_id,
        "project_code": "L1-ICE-BREAKER",
        "project_kind": "SPEECH",
        "level": 1,
        "speech_minutes": 6,
        "delivered_at": "2026-09-08T18:30:00Z",
        "expected_education_path_version": expected_education_path_version,
    }
    payload.update(overrides)
    return payload


def meeting_payload(club_id: str, expected_club_version: int, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/meetings."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "scheduled_at": MEETING_AT,
        "duration_minutes": DEFAULT_MEETING_MINUTES,
        "venue_name": TEST_VENUE_NAME,
        "expected_club_version": expected_club_version,
    }
    payload.update(overrides)
    return payload


def role_assignment_payload(meeting_id: str, member_id: str, expected_meeting_version: int, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/role-assignments."""
    payload: Dict[str, Any] = {
        "meeting_id": meeting_id,
        "member_id": member_id,
        "role_code": "TIMER",
        "expected_meeting_version": expected_meeting_version,
    }
    payload.update(overrides)
    return payload


def officer_term_payload(club_id: str, member_id: str, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/officer-terms."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "member_id": member_id,
        "office": "PRESIDENT",
    }
    payload.update(overrides)
    return payload


def contest_payload(**overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/contests."""
    payload: Dict[str, Any] = {
        "contest_level": "CLUB",
        "contest_type": "INTERNATIONAL_SPEECH",
        "district_number": TEST_DISTRICT_NUMBER,
        "division_code": TEST_DIVISION_CODE,
        "scheduled_at": CONTEST_AT,
    }
    payload.update(overrides)
    return payload


def contest_entry_payload(contest_id: str, member_id: str, club_id: str, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/contest-entries."""
    payload: Dict[str, Any] = {
        "contest_id": contest_id,
        "member_id": member_id,
        "club_id": club_id,
        "speech_title": "The Long Road",
    }
    payload.update(overrides)
    return payload


def ballot_payload(judge_member_id: str, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/contest-entries/{id}/ballots."""
    payload: Dict[str, Any] = {
        "judge_member_id": judge_member_id,
        "content_score": 90,
        "delivery_score": 80,
        "language_score": 70,
    }
    payload.update(overrides)
    return payload


def area_visit_payload(club_id: str, director_member_id: str, **overrides) -> Dict[str, Any]:
    """Payload for POST /toastmasters/area-visits."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "director_member_id": director_member_id,
        "visit_kind": "AREA_DIRECTOR",
        "scheduled_at": VISIT_AT,
    }
    payload.update(overrides)
    return payload


def completion_review_payload(decision: str, return_reason: Optional[str] = None) -> Dict[str, Any]:
    """Payload for POST /toastmasters/project-completions/{id}/review."""
    payload: Dict[str, Any] = {"decision": decision}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return payload
