"""Officer term endpoints: nomination, election and district training."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import db
import recompute
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("officers", __name__, url_prefix="/toastmasters")

OFFICES = (
    "PRESIDENT",
    "VP_EDUCATION",
    "VP_MEMBERSHIP",
    "VP_PUBLIC_RELATIONS",
    "SECRETARY",
    "TREASURER",
    "SERGEANT_AT_ARMS",
)

TRAINING_DUE_DAYS = 30


def _get_term(term_id):
    return db.get(db.OFFICER_TERMS, term_id)


@bp.get("/officer-terms")
def list_terms():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    terms = list(db.OFFICER_TERMS.values())
    for query_name in ("club_id", "member_id", "term_index"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            if query_name == "term_index":
                try:
                    wanted = int(wanted)
                except (TypeError, ValueError):
                    raise ApiError(
                        "ERR_INVALID_REQUEST", "Query parameter 'term_index' must be an integer."
                    )
            terms = [t for t in terms if t.get(query_name) == wanted]

    terms.sort(key=lambda t: t["created_at"])
    window, total, _ = db.paginate(terms, limit, offset)
    return array(serializers.render_all("officer_term", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/officer-terms/<term_id>")
def get_term(term_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("officer_term", _get_term(term_id)))


@bp.post("/officer-terms")
def nominate():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    club_id = db.require_str(body, "club_id")
    member_id = db.require_str(body, "member_id")
    office = db.require_enum(body, "office", OFFICES)

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))
    auth.require_officer_of_club(principal, club_id)

    # Priority 4: references resolved in body field order.
    club = db.get(db.CLUBS, club_id)
    db.get(db.MEMBERS, member_id)

    term = db.create(
        db.OFFICER_TERMS,
        {
            "club_id": club_id,
            "member_id": member_id,
            "office": office,
            "term_index": club["dues_cycle_index"],
            "status": "NOMINATED",
            "nominated_at": db.utcnow(),
            "elected_at": None,
            "training_due_at": None,
            "trained_at": None,
        },
    )
    return ok(serializers.render("officer_term", term), status=201)


@bp.post("/officer-terms/<term_id>/elect")
def elect(term_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))

    term = _get_term(term_id)
    auth.require_officer_of_club(principal, term["club_id"])

    # Priority 6: an election requires a NOMINATED term.
    if term["status"] != "NOMINATED":
        raise ApiError("ERR_INVALID_STATE")

    club = db.get(db.CLUBS, term["club_id"])

    # Priority 7: the office and the member must both be free for this term.
    for other in recompute.terms_of_club(term["club_id"]):
        if other["id"] == term["id"]:
            continue
        if other["term_index"] != term["term_index"]:
            continue
        if other["status"] not in ("ELECTED", "TRAINED"):
            continue
        if other["office"] == term["office"]:
            raise ApiError("ERR_OFFICE_ALREADY_FILLED")
        if other["member_id"] == term["member_id"]:
            raise ApiError("ERR_OFFICE_ALREADY_FILLED")

    # Priority 15: the election protocol.
    quorum_after_nomination = False
    for meeting in db.MEETINGS.values():
        if meeting["club_id"] != term["club_id"]:
            continue
        if meeting["status"] != "HELD" or not meeting["quorum_met"]:
            continue
        if meeting["held_at"] is not None and meeting["held_at"] > term["nominated_at"]:
            quorum_after_nomination = True
            break
    if not quorum_after_nomination:
        raise ApiError("ERR_ELECTION_QUORUM_NOT_MET")

    nominee = None
    for membership in recompute.memberships_of_club(term["club_id"]):
        if membership["member_id"] == term["member_id"]:
            nominee = membership
            break
    if nominee is None:
        raise ApiError("ERR_ELECTION_QUORUM_NOT_MET")
    if (
        nominee["status"] != "ACTIVE"
        or nominee["dues_paid_through_cycle"] < club["dues_cycle_index"]
    ):
        raise ApiError("ERR_ELECTION_QUORUM_NOT_MET")

    elected_at = db.utcnow()
    term["status"] = "ELECTED"
    term["elected_at"] = elected_at
    term["training_due_at"] = elected_at + timedelta(days=TRAINING_DUE_DAYS)

    recompute.recompute_officer_role(nominee)
    db.touch(term)
    return ok(serializers.render("officer_term", term))


@bp.post("/officer-terms/<term_id>/training")
def record_training(term_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector",))

    term = _get_term(term_id)
    # Priority 2: the director must differ from the officer being trained.
    auth.require_director_not_nominee(principal, term)

    # Priority 6: training requires an ELECTED term.
    if term["status"] != "ELECTED":
        raise ApiError("ERR_INVALID_STATE")

    club = db.get(db.CLUBS, term["club_id"])
    if club["good_standing"] not in ("GOOD", "PROBATION"):
        raise ApiError("ERR_CLUB_NOT_IN_GOOD_STANDING")

    term["status"] = "TRAINED"
    term["trained_at"] = db.utcnow()

    for membership in recompute.memberships_of_club(club["id"]):
        if membership["member_id"] == term["member_id"]:
            recompute.recompute_officer_role(membership)
            break

    recompute.touch_club(club)
    db.touch(term)
    return ok(serializers.render("officer_term", term))
