"""Composite setup helpers.

The server starts every test with an empty store, so each helper here builds
its preconditions from scratch through the public API. Setup calls use the
lenient validator so a broken precondition surfaces as "Setup step failed"
rather than as a confusing assertion failure deep inside a test.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CONTEST_AT,
    DEFAULT_MEETING_MINUTES,
    FIRST_CYCLE_CLOSE_AT,
    JOIN_DATE,
    MEETING_AT,
    SECOND_CYCLE_OPENED_AT,
    TEST_AREA_CODE,
    TEST_CLUB_NAME_JUDGE,
    TEST_DIVISION_CODE,
    TEST_VENUE_NAME,
    VISIT_AT,
)
from .factories import (
    area_visit_payload,
    ballot_payload,
    bulk_members_payload,
    completion_review_payload,
    contest_entry_payload,
    contest_payload,
    create_club_payload,
    education_path_payload,
    meeting_payload,
    numbered_members,
    officer_term_payload,
    project_completion_payload,
    role_assignment_payload,
)
from .test_users import (
    TEST_USERS,
    make_club_officer_headers,
    make_district_director_headers,
    make_member_headers,
)

# WorldHeadquarters acts without an ownership clause, so one shared constant is safe.
WHQ = TEST_USERS["world_headquarters_headers"]

# Defaults for meetings that must not collide with the primary meeting slot.
SECOND_MEETING_AT = "2026-09-20T18:30:00Z"
THIRD_MEETING_AT = "2026-09-25T18:30:00Z"


# ======================================================================
# Tier 0 — thin reads
# ======================================================================

def get_club(club_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_club(club_id, headers or WHQ))


def get_membership(membership_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_membership(membership_id, headers or WHQ))


def get_member(member_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_member(member_id, headers or WHQ))


def get_path(path_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_education_path(path_id, headers or WHQ))


def get_completion(completion_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_project_completion(completion_id, headers or WHQ))


def get_meeting(meeting_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_meeting(meeting_id, headers or WHQ))


def get_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_role_assignment(assignment_id, headers or WHQ))


def get_term(term_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_officer_term(term_id, headers or WHQ))


def get_contest(contest_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_contest(contest_id, headers or WHQ))


def get_entry(entry_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_contest_entry(entry_id, headers or WHQ))


def get_visit(visit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_area_visit(visit_id, headers or WHQ))


def list_club_meetings(club_id: str, headers=None) -> List[dict]:
    return get_success_data(api_client.list_meetings(headers or WHQ, {"club_id": club_id}))


def list_memberships_for_club(club_id: str, headers=None) -> List[dict]:
    return get_success_data(api_client.list_memberships(headers or WHQ, {"club_id": club_id}))


def list_paths_for_membership(membership_id: str, headers=None) -> List[dict]:
    return get_success_data(
        api_client.list_education_paths(headers or WHQ, {"membership_id": membership_id})
    )


# Version readers — every write that touches a parent needs the parent's live version.
def club_version(club_id: str) -> int:
    return get_club(club_id)["version"]


def membership_version(membership_id: str) -> int:
    return get_membership(membership_id)["version"]


def path_version(path_id: str) -> int:
    return get_path(path_id)["version"]


def meeting_version(meeting_id: str) -> int:
    return get_meeting(meeting_id)["version"]


# ======================================================================
# Tier 1 — entity creation and state progression
# ======================================================================

def create_organizing_club(**overrides) -> dict:
    """Create a club and return its representation."""
    return get_success_data(api_client.create_club(create_club_payload(**overrides), WHQ), 201)


def enroll_membership(
    club_id: str,
    full_name: str = "Ada Lovelace",
    email: str = "ada@example.org",
    join_date: str = JOIN_DATE,
    first_time_member: bool = True,
    member_id: Optional[str] = None,
    home_area_code: Optional[str] = None,
    pay_dues: bool = False,
) -> dict:
    """Enroll one person into a club; optionally pay the current cycle immediately."""
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "join_date": join_date,
        "first_time_member": first_time_member,
    }
    if member_id is not None:
        payload["member_id"] = member_id
    else:
        payload["full_name"] = full_name
        payload["email"] = email
    if home_area_code is not None:
        payload["home_area_code"] = home_area_code
    membership = get_success_data(api_client.create_membership(payload, WHQ), 201)
    if pay_dues:
        membership = renew_dues(membership["id"], membership["member_id"])
    return membership


def bulk_enroll_paid(
    club_id: str,
    count: int,
    prefix: str = "m",
    start: int = 1,
    pay_dues_immediately: bool = True,
) -> List[dict]:
    """Enroll `count` distinct people through the bulk endpoint. Returns the memberships."""
    payload = bulk_members_payload(club_id, numbered_members(count, prefix, start), pay_dues_immediately)
    result = get_success_data(api_client.bulk_create_memberships(payload, WHQ), 201)
    return result["memberships"]


def renew_dues(membership_id: str, member_id: str) -> dict:
    """Pay the current cycle's dues as the member themselves."""
    return get_success_data(
        api_client.renew_dues(membership_id, make_member_headers(member_id)), 200
    )


def refund_dues(membership_id: str, officer_membership_id: str) -> dict:
    """Reverse the most recent payment as an officer of the membership's club."""
    return get_success_data(
        api_client.refund_dues(membership_id, make_club_officer_headers(officer_membership_id)),
        200,
    )


def close_dues_cycle(
    club_id: str,
    cycle_opened_at: Optional[str] = None,
    cycle_closed_at: Optional[str] = None,
) -> dict:
    payload: Dict[str, Any] = {}
    if cycle_opened_at is not None:
        payload["cycle_opened_at"] = cycle_opened_at
    if cycle_closed_at is not None:
        payload["cycle_closed_at"] = cycle_closed_at
    return get_success_data(api_client.close_cycle(club_id, WHQ, payload), 200)


def charter_club(club_id: str) -> dict:
    return get_success_data(api_client.charter_club(club_id, WHQ), 200)


def setup_club_with_officer(
    club_kwargs: Optional[Dict[str, Any]] = None,
    member_name: str = "Ada Lovelace",
    email: str = "ada@example.org",
) -> Tuple[dict, dict, str]:
    """Organizing club + one paid member who can act as its ClubOfficer.

    Returns (club, membership, member_id).
    """
    club = create_organizing_club(**(club_kwargs or {}))
    membership = enroll_membership(club["id"], full_name=member_name, email=email, pay_dues=True)
    return club, membership, membership["member_id"]


def setup_club_with_paid_members(
    count: int,
    club_kwargs: Optional[Dict[str, Any]] = None,
    prefix: str = "m",
    start: int = 1,
) -> Tuple[dict, List[dict]]:
    """Organizing club + `count` memberships with the current cycle paid.

    Returns (club, memberships).
    """
    club = create_organizing_club(**(club_kwargs or {}))
    memberships = bulk_enroll_paid(club["id"], count, prefix=prefix, start=start)
    return club, memberships


def setup_chartered_club(count: int = 20, prefix: str = "r") -> Tuple[dict, List[dict]]:
    """Chartered club with `count` dues-paid memberships."""
    club, memberships = setup_club_with_paid_members(count, prefix=prefix)
    club = charter_club(club["id"])
    return club, memberships


def setup_club_with_lapsed_member(
    club_kwargs: Optional[Dict[str, Any]] = None,
    closes: int = 2,
) -> Tuple[dict, dict]:
    """Club + one member who paid cycle 0 and was then lapsed by `closes` closes.

    Returns (club, membership) with the membership in status LAPSED.
    """
    club, membership, _ = setup_club_with_officer(club_kwargs)
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    if closes > 1:
        close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)
    return get_club(club["id"]), get_membership(membership["id"])


# ======================================================================
# Tier 2 — education hierarchy and completion lifecycle
# ======================================================================

def create_path(
    membership_id: str,
    member_id: str,
    path_code: str = "DYNAMIC_LEADERSHIP",
) -> dict:
    """Enroll a membership in a path as the member themselves."""
    payload = education_path_payload(membership_id, membership_version(membership_id), path_code=path_code)
    return get_success_data(api_client.create_education_path(payload, make_member_headers(member_id)), 201)


def log_completion(
    path_id: str,
    member_id: str,
    project_code: str = "L1-ICE-BREAKER",
    project_kind: str = "SPEECH",
    level: int = 1,
    speech_minutes: int = 5,
    delivered_at: str = "2026-09-08T18:30:00Z",
    evaluator_member_id: Optional[str] = None,
) -> dict:
    """Log a completion against a path as the member who owns it."""
    overrides: Dict[str, Any] = {
        "project_code": project_code,
        "project_kind": project_kind,
        "level": level,
        "speech_minutes": speech_minutes,
        "delivered_at": delivered_at,
    }
    if evaluator_member_id is not None:
        overrides["evaluator_member_id"] = evaluator_member_id
    payload = project_completion_payload(path_id, path_version(path_id), **overrides)
    return get_success_data(api_client.create_project_completion(payload, make_member_headers(member_id)), 201)


def record_evaluation(
    completion_id: str,
    evaluator_member_id: str,
    evaluation_summary: str = "Clear structure and a strong opening",
) -> dict:
    """Record the evaluator's written evaluation as that evaluator."""
    return get_success_data(
        api_client.record_evaluation(
            completion_id,
            {"evaluation_summary": evaluation_summary},
            make_member_headers(evaluator_member_id),
        ),
        200,
    )


def review_completion(
    completion_id: str,
    officer_membership_id: str,
    decision: str,
    return_reason: Optional[str] = None,
):
    """Raw officer review — returns the response so callers can assert failures."""
    return api_client.review_completion(
        completion_id,
        completion_review_payload(decision, return_reason),
        make_club_officer_headers(officer_membership_id),
    )


def approve_completion(completion_id: str, officer_membership_id: str) -> dict:
    return get_success_data(review_completion(completion_id, officer_membership_id, "APPROVE"), 200)


def approve_completions(
    path_id: str,
    member_id: str,
    officer_membership_id: str,
    specs: Sequence[Dict[str, Any]],
    evaluator_member_id: Optional[str] = None,
) -> List[dict]:
    """Log, evaluate and approve each spec in order. Returns the approved completions."""
    approved = []
    for spec in specs:
        completion = log_completion(path_id, member_id, evaluator_member_id=evaluator_member_id, **spec)
        record_evaluation(completion["id"], evaluator_member_id or member_id, "Reviewed and accepted")
        approved.append(approve_completion(completion["id"], officer_membership_id))
    return approved


def setup_member_with_path(
    club_kwargs: Optional[Dict[str, Any]] = None,
    path_code: str = "DYNAMIC_LEADERSHIP",
) -> Tuple[dict, dict, str, dict]:
    """Organizing club + one paid member + one ACTIVE path at LEVEL_1.

    Returns (club, membership, member_id, path).
    """
    club, membership, member_id = setup_club_with_officer(club_kwargs)
    path = create_path(membership["id"], member_id, path_code)
    return club, membership, member_id, path


def setup_path_with_approved_level_1(
    club_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[dict, dict, str, dict, List[dict], str]:
    """Club + one dues-paid member + a path holding two APPROVED LEVEL_1 speech completions.

    The paid member acts as their own club's officer. The evaluator is a second
    member of the same club whose dues are still unpaid, so the club's paid roster
    stays at exactly one membership.
    Returns (club, membership, member_id, path, completions, evaluator_member_id).
    """
    club = create_organizing_club(**(club_kwargs or {}))
    officer_ms = bulk_enroll_paid(club["id"], 1, prefix="e")[0]
    evaluator = enroll_membership(
        club["id"],
        full_name="Evaluator One",
        email="evaluator@example.org",
        first_time_member=True,
        pay_dues=False,
    )
    path = create_path(officer_ms["id"], officer_ms["member_id"])
    completions = approve_completions(
        path["id"],
        officer_ms["member_id"],
        officer_ms["id"],
        [
            {"project_code": "L1-ICE-BREAKER", "project_kind": "SPEECH", "level": 1, "speech_minutes": 6},
            {"project_code": "L1-WRITING-A-SPEECH", "project_kind": "SPEECH", "level": 1, "speech_minutes": 5},
        ],
        evaluator_member_id=evaluator["member_id"],
    )
    return (
        get_club(club["id"]),
        officer_ms,
        officer_ms["member_id"],
        get_path(path["id"]),
        completions,
        evaluator["member_id"],
    )


def setup_path_at_level_2_with_level_2_completion(
    club_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[dict, dict, str, dict, dict, str]:
    """Club + paid member + path advanced to LEVEL_2 holding an APPROVED LEVEL_2 completion.

    Returns (club, membership, member_id, path, level_2_completion, evaluator_member_id).
    """
    club, membership, member_id, path, _, evaluator_member_id = setup_path_with_approved_level_1(club_kwargs)
    advanced = get_success_data(
        api_client.advance_level(
            path["id"],
            {"expected_education_path_version": path_version(path["id"])},
            make_member_headers(member_id),
        ),
        200,
    )
    assert advanced["level"] == "LEVEL_2", f"setup: expected LEVEL_2, got {advanced['level']}"
    completion = log_completion(
        path["id"],
        member_id,
        project_code="L2-ACTIVE-LISTENING",
        project_kind="SPEECH",
        level=2,
        speech_minutes=5,
        delivered_at="2026-09-15T18:30:00Z",
        evaluator_member_id=evaluator_member_id,
    )
    record_evaluation(completion["id"], evaluator_member_id, "Good listening demonstration")
    approved = approve_completion(completion["id"], membership["id"])
    return get_club(club["id"]), membership, member_id, get_path(path["id"]), approved, evaluator_member_id


# ======================================================================
# Tier 3 — meetings, roles and quorum
# ======================================================================

def schedule_meeting(
    club_id: str,
    officer_membership_id: str,
    scheduled_at: str = MEETING_AT,
    duration_minutes: int = DEFAULT_MEETING_MINUTES,
    venue_name: str = TEST_VENUE_NAME,
    theme: Optional[str] = None,
):
    """Raw meeting creation — returns the response so callers can assert failures."""
    overrides: Dict[str, Any] = {
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "venue_name": venue_name,
    }
    if theme is not None:
        overrides["theme"] = theme
    payload = meeting_payload(club_id, club_version(club_id), **overrides)
    return api_client.create_meeting(payload, make_club_officer_headers(officer_membership_id))


def create_meeting(
    club_id: str,
    officer_membership_id: str,
    scheduled_at: str = MEETING_AT,
    duration_minutes: int = DEFAULT_MEETING_MINUTES,
    venue_name: str = TEST_VENUE_NAME,
) -> dict:
    response = schedule_meeting(club_id, officer_membership_id, scheduled_at, duration_minutes, venue_name)
    return get_success_data(response, 201)


def close_meeting(
    meeting_id: str,
    officer_membership_id: str,
    outcome: str,
    attendance_count: Optional[int] = None,
    attendee_member_ids: Optional[List[str]] = None,
):
    """Raw close — returns the response so callers can assert failures."""
    payload: Dict[str, Any] = {"outcome": outcome}
    if attendance_count is not None:
        payload["attendance_count"] = attendance_count
    if attendee_member_ids is not None:
        payload["attendee_member_ids"] = attendee_member_ids
    return api_client.close_meeting(meeting_id, payload, make_club_officer_headers(officer_membership_id))


def hold_meeting(
    meeting_id: str,
    officer_membership_id: str,
    attendee_member_ids: List[str],
    attendance_count: Optional[int] = None,
) -> dict:
    count = attendance_count if attendance_count is not None else max(5, len(attendee_member_ids))
    return get_success_data(
        close_meeting(meeting_id, officer_membership_id, "HELD", count, attendee_member_ids), 200
    )


def hold_quorate_meeting(
    club_id: str,
    officer_membership_id: str,
    attendee_member_ids: List[str],
    scheduled_at: str = MEETING_AT,
) -> dict:
    """Schedule a meeting and close it as HELD with a quorum, in one step."""
    meeting = create_meeting(club_id, officer_membership_id, scheduled_at=scheduled_at)
    return hold_meeting(meeting["id"], officer_membership_id, attendee_member_ids)


def assign_role(
    meeting_id: str,
    officer_membership_id: str,
    member_id: str,
    role_code: str = "TIMER",
):
    """Raw assignment — returns the response so callers can assert failures."""
    payload = role_assignment_payload(meeting_id, member_id, meeting_version(meeting_id), role_code=role_code)
    return api_client.create_role_assignment(payload, make_club_officer_headers(officer_membership_id))


def create_assignment(
    meeting_id: str,
    officer_membership_id: str,
    member_id: str,
    role_code: str = "TIMER",
) -> dict:
    return get_success_data(assign_role(meeting_id, officer_membership_id, member_id, role_code), 201)


def release_assignment(assignment_id: str, officer_membership_id: str, reason: str = "Member unavailable"):
    """Raw release — returns the response so callers can assert failures."""
    return api_client.release_role_assignment(
        assignment_id,
        {"released_reason": reason},
        make_club_officer_headers(officer_membership_id),
    )


# ======================================================================
# Tier 3 — officer terms
# ======================================================================

def nominate_officer(club_id: str, officer_membership_id: str, member_id: str, office: str) -> dict:
    payload = officer_term_payload(club_id, member_id, office=office)
    return get_success_data(
        api_client.create_officer_term(payload, make_club_officer_headers(officer_membership_id)), 201
    )


def elect_officer(term_id: str, officer_membership_id: str):
    """Raw election — returns the response so callers can assert failures."""
    return api_client.elect_officer(term_id, make_club_officer_headers(officer_membership_id))


def train_officer(term_id: str, director_member_id: str):
    """Raw training — returns the response so callers can assert failures."""
    return api_client.record_officer_training(term_id, make_district_director_headers(director_member_id))


def setup_elected_officer(
    club_id: str,
    officer_membership_id: str,
    member_id: str,
    office: str = "PRESIDENT",
    attendee_member_ids: Optional[List[str]] = None,
    scheduled_at: str = MEETING_AT,
) -> dict:
    """Nominate, hold a quorate meeting after the nomination, then elect."""
    term = nominate_officer(club_id, officer_membership_id, member_id, office)
    hold_quorate_meeting(
        club_id, officer_membership_id, attendee_member_ids or [member_id], scheduled_at=scheduled_at
    )
    return get_success_data(elect_officer(term["id"], officer_membership_id), 200)


# ======================================================================
# Tier 3 — contests
# ======================================================================

def create_club_contest(
    club_id: str,
    director_member_id: str,
    contest_type: str = "INTERNATIONAL_SPEECH",
    division_code: str = TEST_DIVISION_CODE,
    area_code: str = TEST_AREA_CODE,
    scheduled_at: str = CONTEST_AT,
) -> dict:
    payload = contest_payload(
        club_id=club_id,
        contest_level="CLUB",
        contest_type=contest_type,
        division_code=division_code,
        area_code=area_code,
        scheduled_at=scheduled_at,
    )
    return get_success_data(
        api_client.create_contest(payload, make_district_director_headers(director_member_id)), 201
    )


def enter_contest(
    contest_id: str,
    member_id: str,
    club_id: str,
    speech_title: str = "The Long Road",
):
    """Raw entry — returns the response so callers can assert failures."""
    payload = contest_entry_payload(contest_id, member_id, club_id, speech_title=speech_title)
    return api_client.create_contest_entry(payload, make_member_headers(member_id))


def create_entry(contest_id: str, member_id: str, club_id: str, speech_title: str = "The Long Road") -> dict:
    return get_success_data(enter_contest(contest_id, member_id, club_id, speech_title), 201)


def record_ballot(
    entry_id: str,
    judge_member_id: str,
    content_score: int = 90,
    delivery_score: int = 80,
    language_score: int = 70,
):
    """Raw ballot — returns the response so callers can assert failures."""
    payload = ballot_payload(
        judge_member_id,
        content_score=content_score,
        delivery_score=delivery_score,
        language_score=language_score,
    )
    return api_client.record_ballot(entry_id, payload, make_district_director_headers(judge_member_id))


def setup_judge_member(prefix: str = "judge") -> Tuple[dict, str]:
    """A separate club holding one paid member who can judge other clubs' contests.

    Returns (club, member_id).
    """
    club = create_organizing_club(club_name=TEST_CLUB_NAME_JUDGE, division_code="H", area_code="H-9", venue_name="Harbor Hall")
    memberships = bulk_enroll_paid(club["id"], 1, prefix=prefix)
    return club, memberships[0]["member_id"]


def setup_contest_with_entries(
    entrant_count: int = 2,
    entrant_prefix: str = "c",
) -> Tuple[dict, dict, List[dict], str, str]:
    """Club + paid members + a SCHEDULED club contest with one entry per entrant.

    Returns (club, contest, entries, judge_member_id, first_entrant_member_id).
    """
    club, memberships = setup_club_with_paid_members(entrant_count, prefix=entrant_prefix)
    _, judge_member_id = setup_judge_member(prefix=f"{entrant_prefix}-judge")
    contest = create_club_contest(club["id"], judge_member_id)
    entries = [
        create_entry(contest["id"], ms["member_id"], club["id"], f"Speech {index + 1}")
        for index, ms in enumerate(memberships)
    ]
    return club, contest, entries, judge_member_id, memberships[0]["member_id"]


# ======================================================================
# Tier 3 — governance visits
# ======================================================================

def schedule_visit(
    club_id: str,
    director_member_id: str,
    visit_kind: str = "AREA_DIRECTOR",
    scheduled_at: str = VISIT_AT,
) -> dict:
    payload = area_visit_payload(club_id, director_member_id, visit_kind=visit_kind, scheduled_at=scheduled_at)
    return get_success_data(
        api_client.create_area_visit(payload, make_district_director_headers(director_member_id)), 201
    )


def complete_visit(visit_id: str, director_member_id: str, findings: str = "Reviewed the club's records"):
    """Raw completion — returns the response so callers can assert failures."""
    return api_client.complete_area_visit(
        visit_id, {"findings": findings}, make_district_director_headers(director_member_id)
    )


# ======================================================================
# Tier 4 — accumulation / threshold targeting
# ======================================================================

def setup_club_at_roster_boundary(paid_members: int) -> Tuple[dict, List[dict]]:
    """Club with exactly `paid_members` dues-paid memberships and a held organizing meeting."""
    club, memberships = setup_club_with_paid_members(paid_members, prefix="r")
    return club, memberships


def setup_score_36_club(paid_members: int = 20, prefix: str = "s") -> dict:
    """Club with `paid_members` paid members and nothing else, closed once.

    The cycle-close recomputation leaves a score of 36 and, for a club that is
    already CHARTERED, revokes it.
    """
    club, _ = setup_club_with_paid_members(paid_members, prefix=prefix)
    return close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)


def setup_club_with_trained_officers(
    officer_count: int = 4,
    paid_members: int = 20,
    prefix: str = "o",
) -> Tuple[dict, List[dict], List[dict], str]:
    """Club + `paid_members` paid members + `officer_count` ELECTED-and-TRAINED terms.

    Returns (club, memberships, terms, director_member_id).
    """
    club, memberships = setup_club_with_paid_members(paid_members, prefix=prefix)
    officer_ms = memberships[0]
    # The training director must be someone other than the officer being trained.
    _, director_member_id = setup_judge_member(prefix=f"{prefix}-dir")

    offices = ["PRESIDENT", "VP_EDUCATION", "VP_MEMBERSHIP", "VP_PUBLIC_RELATIONS", "SECRETARY"]
    terms = []
    for index in range(officer_count):
        terms.append(
            nominate_officer(
                club["id"], officer_ms["id"], memberships[index]["member_id"], offices[index % len(offices)]
            )
        )
    hold_quorate_meeting(club["id"], officer_ms["id"], [ms["member_id"] for ms in memberships[:6]])
    elected = []
    for term in terms:
        elected.append(get_success_data(elect_officer(term["id"], officer_ms["id"]), 200))
    trained = []
    for term in elected:
        trained.append(get_success_data(train_officer(term["id"], director_member_id), 200))
    return get_club(club["id"]), memberships, trained, director_member_id
