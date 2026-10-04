"""Club petitioning, charter prerequisites and the charter/revocation lifecycle."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_same_instant,
    bulk_enroll_paid,
    charter_club,
    close_dues_cycle,
    create_organizing_club,
    get_club,
    get_membership,
    get_success_data,
    is_valid_uuid,
    make_member_headers,
    setup_club_with_paid_members,
    validate_error,
    validate_success,
)
from test_helpers.constants import FIRST_CYCLE_CLOSE_AT


def test_club_creation_applies_organizing_defaults(api, whq_headers):
    """PRD §3.1: "The newly created club is `ORGANIZING`, with `good_standing` and
    `cycle_open_standing` both `GOOD`, `dues_cycle_index` 0, `cycle_closed_at` null
    and `coaching_status` `NONE`."
    PRD §3.1: "Its `good_standing_score` is 0 at this point, which is exactly right:
    no membership, officer, meeting or completion rows exist yet, so every weighted
    component contributes nothing."
    PRD §2.6: "while a club is `ORGANIZING` its `charter_date` is null."

    Design: Corner/entities/club_create_applies_defaults_and_system_fields
    """
    payload = {
        "club_name": "Riverside Voices",
        "club_type": "COMMUNITY",
        "district_number": "42",
        "division_code": "C",
        "area_code": "C-3",
        "venue_name": "Riverside Library",
        "club_dues_cents": 3000,
        "cycle_opened_at": "2026-09-01T00:00:00Z",
    }
    response = api.create_club(payload, whq_headers)
    club = validate_success(response, 201)
    assert response.json()["response_type"] == "object", "a single club must be response_type object"

    assert is_valid_uuid(club["id"]), f"id must be a server-minted UUID, got {club['id']!r}"
    assert club["charter_status"] == "ORGANIZING"
    assert club["good_standing"] == "GOOD"
    assert club["cycle_open_standing"] == "GOOD"
    assert club["dues_cycle_index"] == 0
    assert club["cycle_closed_at"] is None
    assert club["charter_date"] is None
    assert club["coaching_status"] == "NONE"
    assert club["good_standing_score"] == 0
    assert_same_instant(club["cycle_opened_at"], "2026-09-01T00:00:00Z", "cycle_opened_at")


def test_club_get_unknown_id_returns_not_found(api, whq_headers):
    """PRD §2.10: "Third, the resource named in the path must exist, otherwise
    `ERR_NOT_FOUND`; this applies to every endpoint whose path contains an `id`."

    Design: Corner/entities/club_get_unknown_id_returns_not_found
    """
    response = api.get_club(NON_EXISTENT_UUID, whq_headers)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)
    assert response.json()["response_type"] == "error", "errors must carry response_type error"


def test_charter_requires_organizing_meeting(api, whq_headers):
    """PRD §3.1: "The organizing meeting must have been held — `organizing_meeting_at`
    must be set — and at least 3 prospective members must have attended it, that is
    `organizing_meeting_attendees` must be at least 3; a petition that arrives before
    that meeting has happened is refused with `ERR_ORGANIZING_MEETING_REQUIRED`."

    Design: Corner/errors/organizing_meeting_required_before_charter
    """
    club = create_organizing_club(organizing_meeting_at=None, organizing_meeting_attendees=None)

    response = api.charter_club(club["id"], whq_headers)
    validate_error(response, ApiErrorId.ERR_ORGANIZING_MEETING_REQUIRED)
    assert get_club(club["id"])["charter_status"] == "ORGANIZING", (
        "a refused charter must leave the club ORGANIZING"
    )


def test_corporate_club_without_sponsor_name_cannot_charter(api, whq_headers):
    """PRD §3.1: "A `CORPORATE` club must carry a `corporate_sponsor_name`; for the
    other three types the field stays null."
    PRD §3.1: "A corporate club with no `corporate_sponsor_name` is refused with
    `ERR_CORPORATE_SPONSOR_REQUIRED`."

    Design: Corner/errors/corporate_sponsor_required_for_corporate_club
    """
    club = create_organizing_club(
        club_name="Northwind Club",
        club_type="CORPORATE",
        area_code="C-4",
        venue_name="Northwind Campus",
        organizing_meeting_attendees=12,
    )
    bulk_enroll_paid(club["id"], 20, prefix="n")
    assert get_club(club["id"])["paid_member_count"] == 20, "the roster requirement must already hold"

    response = api.charter_club(club["id"], whq_headers)
    validate_error(response, ApiErrorId.ERR_CORPORATE_SPONSOR_REQUIRED)


def test_charter_blocked_when_sponsor_not_chartered(api, whq_headers):
    """PRD §3.1: "And when the petition names a `sponsor_club_id`, that sponsor must
    itself be `CHARTERED` with `good_standing` `GOOD`; a sponsor that is suspended,
    revoked, on probation or otherwise not in good standing produces
    `ERR_SPONSOR_NOT_IN_GOOD_STANDING`."

    Design: Corner/errors/sponsor_club_not_chartered_in_good_standing_blocks_charter
    """
    sponsor = create_organizing_club(
        club_name="Harbor Masters",
        division_code="H",
        area_code="H-9",
        venue_name="Harbor Hall",
    )
    assert get_club(sponsor["id"])["charter_status"] == "ORGANIZING", "the sponsor must not be chartered"

    club = create_organizing_club(sponsor_club_id=sponsor["id"])
    bulk_enroll_paid(club["id"], 20, prefix="r")

    response = api.charter_club(club["id"], whq_headers)
    validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_IN_GOOD_STANDING)
    assert get_club(club["id"])["charter_status"] == "ORGANIZING"


def test_charter_refused_below_twenty_paid_members(api, whq_headers):
    """PRD §3.1: "The roster must be real: `paid_member_count` must be at least 20
    dues-paid memberships, and a petition that falls short is refused with
    `ERR_CHARTER_MINIMUM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/charter_roster_minimum_exactly_twenty_paid_members
    """
    club, _ = setup_club_with_paid_members(19, prefix="r")
    assert get_club(club["id"])["paid_member_count"] == 19, "setup: 19 dues-paid memberships"

    response = api.charter_club(club["id"], whq_headers)
    validate_error(response, ApiErrorId.ERR_CHARTER_MINIMUM_NOT_MET)
    assert get_club(club["id"])["charter_status"] == "ORGANIZING"


def test_charter_granted_at_exactly_twenty_paid_members(api, whq_headers):
    """PRD §3.1: "The roster must be real: `paid_member_count` must be at least 20
    dues-paid memberships, and a petition that falls short is refused with
    `ERR_CHARTER_MINIMUM_NOT_MET`."
    PRD §3.1: "Granting a charter moves the club from `ORGANIZING` to `CHARTERED` in
    one atomic operation. `charter_date` is stamped with the request timestamp,
    `cycle_open_standing` is set to the club's current `good_standing`, and the roster
    is activated: every membership of that club that is `PENDING` with `dues_status`
    `PAID` becomes `ACTIVE`."

    Design: Difficulty/boundary_precision_check/charter_roster_minimum_exactly_twenty_paid_members
    """
    club, memberships = setup_club_with_paid_members(19, prefix="r")
    validate_error(api.charter_club(club["id"], whq_headers), ApiErrorId.ERR_CHARTER_MINIMUM_NOT_MET)

    extra = bulk_enroll_paid(club["id"], 1, prefix="r", start=20)
    assert len(extra) == 1, "the twentieth row must be committed"
    assert get_club(club["id"])["paid_member_count"] == 20

    chartered = get_success_data(api.charter_club(club["id"], whq_headers), 200)
    assert chartered["charter_status"] == "CHARTERED", (
        "the twentieth paid membership must let the same call succeed"
    )
    assert chartered["charter_date"] is not None, "charter_date must be stamped on grant"
    assert chartered["cycle_open_standing"] == chartered["good_standing"]
    assert get_membership(memberships[0]["id"])["status"] == "ACTIVE", (
        "a PENDING membership whose dues are PAID is activated by the grant"
    )


def test_revoked_club_refuses_dues_renewal(api, whq_headers):
    """PRD §3.1: "when it is strictly below 40, a club that is `CHARTERED` or
    `SUSPENDED` moves to `REVOKED`, which is terminal."
    PRD §3.3: "a club whose `charter_status` is `REVOKED` refuses it with
    `ERR_CLUB_REVOKED`."

    Design: Corner/errors/club_revoked_blocks_dues_renewal
    """
    club, memberships = setup_club_with_paid_members(20, prefix="r")
    charter_club(club["id"])

    # PRD §2.7: the cycle-close variant of the score "counts only rows created at
    # or before `cycle_closed_at`".  Every fixture row here is created at request
    # time, so the close must be stamped after the roster it is judging.
    closed = close_dues_cycle(club["id"], "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert closed["good_standing_score"] == 36, "30 dues points + 6 points from 3 recognition points"
    assert closed["charter_status"] == "REVOKED", "a score below 40 revokes a chartered club"

    membership = memberships[0]
    invoice_before = get_membership(membership["id"])["dues_status"]
    response = api.renew_dues(membership["id"], make_member_headers(membership["member_id"]))
    validate_error(response, ApiErrorId.ERR_CLUB_REVOKED)
    assert get_membership(membership["id"])["dues_status"] == invoice_before, (
        "the refused renewal must leave the invoice untouched"
    )
