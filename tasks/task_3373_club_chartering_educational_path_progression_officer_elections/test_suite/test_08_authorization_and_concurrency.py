"""Role-scope authorization and the four optimistic-concurrency write paths."""
from test_helpers import (
    ApiErrorId,
    club_version,
    create_assignment,
    create_meeting,
    create_organizing_club,
    enroll_membership,
    get_meeting,
    list_club_meetings,
    make_club_officer_headers,
    make_member_headers,
    schedule_meeting,
    setup_club_with_officer,
    setup_club_with_paid_members,
    validate_error,
)
from test_helpers.constants import MEETING_AT, TEST_VENUE_NAME


def test_member_role_cannot_close_a_meeting(api, whq_headers):
    """PRD §2.1: "A request whose declared role is not listed on the endpoint it
    targets, or that fails the ownership clause attached to that role, is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_role_cannot_close_meeting
    """
    club, membership, member_id = setup_club_with_officer()
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_AT)

    response = api.close_meeting(
        meeting["id"], {"outcome": "HELD", "attendance_count": 6}, make_member_headers(member_id)
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_meeting(meeting["id"])["status"] == "SCHEDULED", "the refused close must change nothing"


def test_officer_of_another_club_cannot_manage_this_club(api, whq_headers):
    """PRD §2.1: "When `X-User-Role` is `ClubOfficer`, `X-User-ID` is the `id` of the
    acting `Membership`; ownership checks on any resource that references a `Membership`
    compare the resource's foreign-key field to `X-User-ID`, which in practice means the
    acting membership's `club_id` must equal the club targeted by the operation, and
    club-scoped writes are refused for a membership of any other club."

    Design: Corner/rbac/officer_of_another_club_cannot_manage_this_club
    """
    club = create_organizing_club()
    other_club = create_organizing_club(
        club_name="Harbor Masters", division_code="H", area_code="H-9", venue_name="Harbor Hall"
    )
    outsider = enroll_membership(
        other_club["id"], full_name="Outsider Officer", email="outsider@example.org", pay_dues=True
    )

    response = schedule_meeting(club["id"], outsider["id"], scheduled_at=MEETING_AT)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert list_club_meetings(club["id"]) == [], "no meeting may be created for the first club"


def test_meeting_create_with_a_stale_club_version_is_refused(api, whq_headers):
    """PRD §2.8: "Scheduling a meeting requires `expected_club_version`, which must
    equal the target club's current `version`."
    PRD §2.8: "when the supplied value differs from the parent entity's current
    `version`, the write is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/stale_club_version_rejected_on_meeting_create
    """
    club, membership, member_id = setup_club_with_officer()
    stale_version = club_version(club["id"])
    create_meeting(club["id"], membership["id"], scheduled_at=MEETING_AT)

    response = api.create_meeting(
        {
            "club_id": club["id"],
            "scheduled_at": "2026-09-20T18:30:00Z",
            "duration_minutes": 90,
            "venue_name": TEST_VENUE_NAME,
            "expected_club_version": stale_version,
        },
        make_club_officer_headers(membership["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert len(list_club_meetings(club["id"])) == 1, (
        "the second window does not overlap the first, so only the stale version explains the refusal"
    )


def test_assignment_create_with_a_stale_meeting_version_is_refused(api, whq_headers):
    """PRD §2.8: "Adding a role assignment requires `expected_meeting_version`, which
    must equal the target meeting's current `version`."
    PRD §2.8: "when the supplied value differs from the parent entity's current
    `version`, the write is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/stale_meeting_version_rejected_on_assignment_create
    """
    club, memberships = setup_club_with_paid_members(2, prefix="t")
    officer_ms, other_ms = memberships[0], memberships[1]
    meeting = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_AT)
    stale_version = meeting["version"]
    create_assignment(meeting["id"], officer_ms["id"], officer_ms["member_id"], "TIMER")

    response = api.create_role_assignment(
        {
            "meeting_id": meeting["id"],
            "member_id": other_ms["member_id"],
            "role_code": "GRAMMARIAN",
            "expected_meeting_version": stale_version,
        },
        make_club_officer_headers(officer_ms["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert get_meeting(meeting["id"])["filled_role_slots"] == 1, (
        "the second assignment is otherwise legal, so only the stale version explains the refusal"
    )
