"""Clubs: chartering, escrow funding, club-scoped reads and room-stay booking."""

from flask import Blueprint, g, request

import auth
import calc
import derive
import envelope
import ops
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("clubs", __name__)

MEMBER_ROLE_TYPES = ("HEAD_COACH", "ASSISTANT_COACH", "OFFICIAL", "CHAPERONE", "VOLUNTEER")
SCREENING_STATUSES = ("UNSCREENED", "SCREENING_ORDERED", "FLAGGED", "CLEARED", "EXPIRED",
                      "DISQUALIFIED")
MEMBERSHIP_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "LAPSED", "REVOKED")
CONTACT_ELIGIBILITIES = ("ELIGIBLE", "RESTRICTED", "PROHIBITED")
AUDIT_STATUSES = ("SAMPLED", "FINDINGS_ISSUED", "CLOSED_COMPLIANT", "CLOSED_SANCTIONED")
STAY_STATUSES = ("BOOKED", "CANCELLED")

CLUB_SPEC = {
    "name": validate.string(min_len=1, max_len=120),
    "state_code": validate.string(min_len=2, max_len=2, pattern=validate.UPPER2),
    "roster_size_attested": validate.integer(minimum=0),
    "minor_athlete_program": validate.boolean(required=False, default=True),
    "initial_escrow_cents": validate.integer(required=False, minimum=0, default=0),
}


@bp.post("/clubs")
@auth.endpoint("NgbAdmin")
def charter_club():
    data = validate.body(auth.payload(), CLUB_SPEC)
    seed = data["initial_escrow_cents"]
    row = store.new_row(
        name=data["name"],
        state_code=data["state_code"],
        minor_athlete_program=data["minor_athlete_program"],
        roster_size_attested=data["roster_size_attested"],
        escrow_balance_cents=seed,
        total_funded_cents=seed,
        sanction_status="NONE",
        compliance_posture="OPEN",
        compliance_score=None,
        open_finding_count=0,
        critical_open_finding_count=0,
        restricted_member_count=0,
        active_assignment_count=0,
    )
    store.CLUBS[row["id"]] = row
    return envelope.created(serialize.club(row))


@bp.post("/clubs/<club_id>/escrow-funding")
@auth.endpoint("NgbAdmin", "ClubAdministrator")
def fund_escrow(club_id):
    club = auth.club(club_id)
    auth.scope(club_id)
    data = validate.body(auth.payload(), {"amount_cents": validate.integer(minimum=1)})
    club["escrow_balance_cents"] += data["amount_cents"]
    club["total_funded_cents"] += data["amount_cents"]
    store.bump(club)
    derive.recompute_club(club)
    return envelope.ok(serialize.club(club))


@bp.get("/clubs/<club_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def read_club(club_id):
    club = auth.club(club_id)
    auth.scope(club_id)
    return envelope.ok(serialize.club(club))


@bp.get("/clubs/<club_id>/members")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def list_club_members(club_id):
    auth.club(club_id)
    auth.scope(club_id)
    args = request.args
    validate.query_enum(args, "screening_status", SCREENING_STATUSES)
    validate.query_enum(args, "membership_status", MEMBERSHIP_STATUSES)
    validate.query_enum(args, "contact_eligibility", CONTACT_ELIGIBILITIES)
    validate.query_enum(args, "role_type", MEMBER_ROLE_TYPES)
    rows = [m for m in store.MEMBERS.values() if m["club_id"] == club_id
            and pagelib.match(m, args, "screening_status")
            and pagelib.match(m, args, "membership_status")
            and pagelib.match(m, args, "contact_eligibility")
            and pagelib.match(m, args, "role_type")]
    return pagelib.page(store.ordered(rows), serialize.member, args)


@bp.get("/clubs/<club_id>/audits")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor")
def list_club_audits(club_id):
    auth.club(club_id)
    auth.scope(club_id)
    args = request.args
    validate.query_enum(args, "status", AUDIT_STATUSES)
    rows = [a for a in store.audits_of_club(club_id) if pagelib.match(a, args, "status")]
    rows = list(reversed(store.ordered(rows)))
    return pagelib.page(rows, serialize.club_audit, args)


@bp.get("/clubs/<club_id>/room-stays")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor")
def list_club_room_stays(club_id):
    auth.club(club_id)
    auth.scope(club_id)
    args = request.args
    validate.query_enum(args, "status", STAY_STATUSES)
    rows = [s for s in store.ROOM_STAYS.values() if s["club_id"] == club_id
            and pagelib.match(s, args, "status")
            and pagelib.match(s, args, "trip_label")
            and pagelib.match(s, args, "room_number")]
    rows.sort(key=lambda s: (s["check_in"], s["created_at"], s["_seq"]))
    return pagelib.page(rows, serialize.room_stay, args)


STAY_SPEC = {
    "occupant_kind": validate.enum(("ADULT_MEMBER", "MINOR_ATHLETE")),
    "trip_label": validate.string(min_len=1, max_len=60),
    "room_number": validate.string(min_len=1, max_len=12),
    "check_in": validate.instant(),
    "check_out": validate.instant(),
    "member_id": validate.string(required=False, min_len=1),
    "minor_athlete_age": validate.integer(required=False, minimum=5, maximum=17),
}


@bp.post("/clubs/<club_id>/room-stays")
@auth.endpoint("ClubAdministrator")
def book_room_stay(club_id):
    club = auth.club(club_id)
    auth.scope(club_id)
    data = validate.body(auth.payload(), STAY_SPEC)
    if data["check_out"] <= data["check_in"]:
        validate.bad("check_out must be strictly after check_in")
    if data["occupant_kind"] == "ADULT_MEMBER":
        if data["member_id"] is None or data["minor_athlete_age"] is not None:
            validate.bad("an ADULT_MEMBER stay carries member_id and no minor_athlete_age")
    else:
        if data["member_id"] is not None or data["minor_athlete_age"] is None:
            validate.bad("a MINOR_ATHLETE stay carries minor_athlete_age and no member_id")

    member = None
    if data["member_id"] is not None:
        member = auth.member(data["member_id"])
    if club["compliance_posture"] == "FROZEN":
        fail("ERR_CLUB_POSTURE_FROZEN", "club posture FROZEN blocks room-stay booking")
    if member is not None:
        if member["screening_status"] == "DISQUALIFIED":
            fail("ERR_MEMBER_DISQUALIFIED", "the occupant is disqualified")
        if derive.has_measure(member["id"], ("PERMANENT", "ACTIVE")):
            fail("ERR_CONTACT_NOT_PERMITTED", "the occupant is under a restriction")

    neighbours = ops.slot_neighbours(club_id, data["trip_label"], data["room_number"],
                                    data["check_in"], data["check_out"])
    for other in neighbours:
        if other["occupant_kind"] != data["occupant_kind"]:
            fail("ERR_MINOR_ADULT_LODGING_PROHIBITED",
                 "an adult member and a minor athlete may not share a room slot")
    if len(neighbours) + 1 > calc.ROOM_SLOT_CAPACITY:
        fail("ERR_ROOM_OCCUPANCY_CONFLICT", "the room slot is already at capacity")

    row = store.new_row(
        club_id=club_id,
        member_id=data["member_id"],
        occupant_kind=data["occupant_kind"],
        minor_athlete_age=data["minor_athlete_age"],
        trip_label=data["trip_label"],
        room_number=data["room_number"],
        check_in=data["check_in"],
        check_out=data["check_out"],
        status="BOOKED",
        cancel_reason=None,
    )
    store.ROOM_STAYS[row["id"]] = row
    return envelope.created(serialize.room_stay(row))
