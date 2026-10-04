"""Club endpoints: creation, reads, chartering, cycle close, coaching queue."""

from flask import Blueprint, request

import auth
import calc
import db
import recompute
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("clubs", __name__, url_prefix="/toastmasters")

CLUB_TYPES = ("COMMUNITY", "CORPORATE", "CAMPUS", "ADVANCED")


def _get_club(club_id):
    return db.get(db.CLUBS, club_id)


@bp.get("/clubs/coaching-queue")
def coaching_queue():
    """Ranked list of clubs a district director should coach next."""
    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector", "WorldHeadquarters"))

    candidates = [
        club
        for club in db.CLUBS.values()
        if club["good_standing"] in ("PROBATION", "NOT_IN_GOOD_STANDING")
        and club["coaching_status"] == "NONE"
    ]
    if not candidates:
        # Priority 19: the queue must be non-empty.
        raise ApiError("ERR_NO_COACHING_CANDIDATES")

    limit_raw = request.args.get("limit")
    limit = 10
    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must lie between 1 and 100.")
    limit = min(limit, calc.QUEUE_LIMIT)

    ranked = calc.coaching_queue_rank(candidates)[:limit]
    return array(serializers.render_all("club", ranked), limit=limit, offset=0,
                 total_count=len(candidates))


@bp.get("/clubs")
def list_clubs():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    clubs = list(db.CLUBS.values())
    filters = (
        ("sponsor_club_id", "sponsor_club_id"),
        ("charter_status", "charter_status"),
        ("good_standing", "good_standing"),
        ("coaching_status", "coaching_status"),
        ("area_code", "area_code"),
    )
    for query_name, field in filters:
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            clubs = [club for club in clubs if club.get(field) == wanted]

    clubs.sort(key=lambda club: club["created_at"])
    window, total, _ = db.paginate(clubs, limit, offset)
    return array(serializers.render_all("club", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/clubs/<club_id>")
def get_club(club_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("club", _get_club(club_id)))


@bp.post("/clubs")
def create_club():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    # Structural validation precedes every business rule (PRD section 2.10).
    club_name = db.require_str(body, "club_name")
    club_type = db.require_enum(body, "club_type", CLUB_TYPES)
    district_number = db.require_str(body, "district_number")
    division_code = db.require_str(body, "division_code")
    area_code = db.require_str(body, "area_code")
    venue_name = db.require_str(body, "venue_name")
    club_dues_cents = db.require_int(body, "club_dues_cents")
    cycle_opened_at = db.parse_dt(db.require(body, "cycle_opened_at"), "cycle_opened_at")
    sponsor_club_id = db.optional(body, "sponsor_club_id")
    corporate_sponsor_name = db.optional(body, "corporate_sponsor_name")
    organizing_meeting_at = db.parse_dt(
        db.optional(body, "organizing_meeting_at"), "organizing_meeting_at"
    )
    organizing_meeting_attendees = db.optional_int(
        body, "organizing_meeting_attendees", 0
    )

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("WorldHeadquarters",))

    # Priority 4: every entity referenced by the payload must exist.
    if sponsor_club_id is not None:
        db.get(db.CLUBS, sponsor_club_id)

    club = db.create(
        db.CLUBS,
        {
            "club_name": club_name,
            "club_type": club_type,
            "corporate_sponsor_name": corporate_sponsor_name,
            "district_number": district_number,
            "division_code": division_code,
            "area_code": area_code,
            "venue_name": venue_name,
            "club_dues_cents": club_dues_cents,
            "sponsor_club_id": sponsor_club_id,
            "organizing_meeting_at": organizing_meeting_at,
            "organizing_meeting_attendees": organizing_meeting_attendees or 0,
            "charter_status": "ORGANIZING",
            "charter_date": None,
            "good_standing": "GOOD",
            "cycle_open_standing": "GOOD",
            "dues_cycle_index": 0,
            "cycle_opened_at": cycle_opened_at,
            "cycle_closed_at": None,
            "coaching_status": "NONE",
            # A brand new club carries no rows, so every weighted component
            # contributes nothing and the score is 0 (PRD section 3.1).
            "good_standing_score": 0,
            "paid_member_count": 0,
            "total_member_count": 0,
            "new_member_count_this_cycle": 0,
            "officer_trained_count": 0,
            "meetings_held_this_cycle": 0,
            "approved_level_completions_this_cycle": 0,
            "contest_participation_count": 0,
            "dcp_recognition_points": 0,
            "dcp_tier": "NONE",
        },
    )
    return ok(serializers.render("club", club), status=201)


@bp.post("/clubs/<club_id>/charter")
def charter_club(club_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("WorldHeadquarters",))

    club = _get_club(club_id)

    # Priority 6: the club must admit the transition.
    if club["charter_status"] not in ("ORGANIZING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")

    reinstating = club["charter_status"] == "SUSPENDED"

    if not reinstating:
        # Priority 10, in the order the scaffold lists the prerequisites.
        if (
            club.get("organizing_meeting_at") is None
            or (club.get("organizing_meeting_attendees") or 0) < 3
        ):
            raise ApiError("ERR_ORGANIZING_MEETING_REQUIRED")
        if club["paid_member_count"] < 20:
            raise ApiError("ERR_CHARTER_MINIMUM_NOT_MET")
        if club["club_type"] == "CORPORATE" and not club.get("corporate_sponsor_name"):
            raise ApiError("ERR_CORPORATE_SPONSOR_REQUIRED")
        sponsor_id = club.get("sponsor_club_id")
        if sponsor_id:
            sponsor = db.CLUBS.get(sponsor_id)
            if (
                sponsor is None
                or sponsor["charter_status"] != "CHARTERED"
                or sponsor["good_standing"] != "GOOD"
            ):
                raise ApiError("ERR_SPONSOR_NOT_IN_GOOD_STANDING")
    else:
        if club["paid_member_count"] < 20:
            raise ApiError("ERR_CHARTER_MINIMUM_NOT_MET")
        if club["good_standing_score"] < 60:
            raise ApiError(
                "ERR_CHARTER_MINIMUM_NOT_MET",
                "Reinstatement requires a good_standing_score of at least 60.",
            )

    now = db.utcnow()
    club["charter_status"] = "CHARTERED"
    club["charter_date"] = now
    # Posture is forced to GOOD at the moment a charter is granted (PRD 2.6).
    club["good_standing"] = "GOOD"
    club["cycle_open_standing"] = "GOOD"

    for membership in recompute.memberships_of_club(club["id"]):
        activated = False
        if not reinstating:
            if membership["status"] == "PENDING" and membership["dues_status"] == "PAID":
                membership["status"] = "ACTIVE"
                activated = True
        else:
            if membership["status"] == "LAPSED":
                membership["status"] = "ACTIVE"
                activated = True
        if activated:
            for path in recompute.paths_of_membership(membership["id"]):
                recompute.activate_path(path)
            db.touch(membership)

    recompute.recompute_club(club)
    db.touch(club)
    return ok(serializers.render("club", club))


@bp.post("/clubs/<club_id>/close-cycle")
def close_cycle(club_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    supplied_opened_at = db.parse_dt(db.optional(body, "cycle_opened_at"), "cycle_opened_at")
    supplied_closed_at = db.parse_dt(db.optional(body, "cycle_closed_at"), "cycle_closed_at")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("WorldHeadquarters",))

    club = _get_club(club_id)
    recompute.close_cycle(club, supplied_opened_at, supplied_closed_at)
    db.touch(club)
    return ok(serializers.render("club", club))
