"""Governance visit endpoints."""

from flask import Blueprint, request

import auth
import db
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("visits", __name__, url_prefix="/toastmasters")

VISIT_KINDS = ("AREA_DIRECTOR", "DIVISION_DIRECTOR", "CLUB_COACH")


def _get_visit(visit_id):
    return db.get(db.VISITS, visit_id)


@bp.get("/area-visits")
def list_visits():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    visits = list(db.VISITS.values())
    for query_name in ("club_id", "director_member_id", "status"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            visits = [v for v in visits if v.get(query_name) == wanted]

    visits.sort(key=lambda v: v["created_at"])
    window, total, _ = db.paginate(visits, limit, offset)
    return array(serializers.render_all("area_visit", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/area-visits/<visit_id>")
def get_visit(visit_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("area_visit", _get_visit(visit_id)))


@bp.post("/area-visits")
def create_visit():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    club_id = db.require_str(body, "club_id")
    director_member_id = db.require_str(body, "director_member_id")
    visit_kind = db.require_enum(body, "visit_kind", VISIT_KINDS)
    scheduled_at = db.parse_dt(db.require(body, "scheduled_at"), "scheduled_at")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector",))

    # Priority 4: references resolved in body field order.
    club = db.get(db.CLUBS, club_id)
    db.get(db.MEMBERS, director_member_id)

    visit = db.create(
        db.VISITS,
        {
            "club_id": club_id,
            "director_member_id": director_member_id,
            "visit_kind": visit_kind,
            "scheduled_at": scheduled_at,
            "status": "SCHEDULED",
            "completed_at": None,
            "findings": None,
        },
    )
    if visit_kind == "CLUB_COACH" and club["coaching_status"] == "FLAGGED":
        club["coaching_status"] = "ASSIGNED"
        db.touch(club)
    return ok(serializers.render("area_visit", visit), status=201)


@bp.post("/area-visits/<visit_id>/complete")
def complete_visit(visit_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    findings = db.require_str(body, "findings")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector",))

    visit = _get_visit(visit_id)
    # Priority 2: only the director who owns the visit may complete it.
    auth.require_director_of_visit(principal, visit)

    # Priority 6: a visit completion requires SCHEDULED.
    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    visit["status"] = "COMPLETED"
    visit["completed_at"] = db.utcnow()
    visit["findings"] = findings

    club = db.get(db.CLUBS, visit["club_id"])
    if visit["visit_kind"] == "CLUB_COACH":
        if club["coaching_status"] != "COACHED":
            club["coaching_status"] = "COACHED"
            db.touch(club)
    else:
        if club["coaching_status"] == "FLAGGED":
            club["coaching_status"] = "ASSIGNED"
            db.touch(club)

    db.touch(visit)
    return ok(serializers.render("area_visit", visit))
