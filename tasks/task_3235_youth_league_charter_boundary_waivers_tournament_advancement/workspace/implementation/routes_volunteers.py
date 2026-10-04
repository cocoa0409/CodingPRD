"""Volunteer, background-screening, and insurance-certificate routes."""
from flask import Blueprint, request

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import volunteer_view, screening_view, certificate_view
from services import (
    SEVERE_OFFENSES, get_league, get_volunteer, get_screening, parse_date, touch,
)

bp = Blueprint("volunteers", __name__)

ROLE_TITLES = {"MANAGER", "COACH", "UMPIRE", "BOARD_MEMBER", "CONCESSIONS"}
OFFENSES = {"NONE", "NONVIOLENT_MISDEMEANOR", "VIOLENT_FELONY", "SEXUAL_OFFENSE", "CHILD_ABUSE"}


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


@bp.post("/leagues/<leagueId>/volunteers")
@require_auth(["LeagueAdministrator"])
def create_volunteer(leagueId):
    get_league(leagueId)
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    role_title = body.get("role_title")
    if not isinstance(full_name, str) or not full_name:
        raise err("ERR_INVALID_REQUEST", "full_name is required")
    if role_title not in ROLE_TITLES:
        raise err("ERR_INVALID_REQUEST", "invalid role_title")
    ts = now_ts()
    vol = {
        "id": new_id(),
        "league_id": leagueId,
        "full_name": full_name,
        "role_title": role_title,
        "status": "REGISTERED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.volunteers[vol["id"]] = vol
    return success_object(volunteer_view(vol), 201)


@bp.get("/leagues/<leagueId>/volunteers")
@require_auth(ANY)
def list_volunteers(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    recs = _sorted(v for v in db.volunteers.values() if v["league_id"] == leagueId)
    total = len(recs)
    return success_list([volunteer_view(v) for v in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/leagues/<leagueId>/volunteers/<volunteerId>/screenings")
@require_auth(["LeagueAdministrator"])
def create_screening(leagueId, volunteerId):
    get_league(leagueId)
    vol = get_volunteer(leagueId, volunteerId)
    body = request.get_json(silent=True) or {}
    offense_category = body.get("offense_category")
    valid_from = body.get("valid_from")
    valid_through = body.get("valid_through")
    if offense_category not in OFFENSES:
        raise err("ERR_INVALID_REQUEST", "invalid offense_category")
    if not isinstance(valid_from, str) or not isinstance(valid_through, str):
        raise err("ERR_INVALID_REQUEST", "valid_from and valid_through are required")
    try:
        vf = parse_date(valid_from)
        vt = parse_date(valid_through)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "dates must be YYYY-MM-DD")
    if vt < vf:
        raise err("ERR_INVALID_REQUEST", "valid_through must be >= valid_from")
    ts = now_ts()
    scr = {
        "id": new_id(),
        "volunteer_id": vol["id"],
        "offense_category": offense_category,
        "valid_from": valid_from,
        "valid_through": valid_through,
        "auto_flagged": offense_category in SEVERE_OFFENSES,
        "status": "SUBMITTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.screenings[scr["id"]] = scr
    return success_object(screening_view(scr), 201)


@bp.get("/leagues/<leagueId>/volunteers/<volunteerId>/screenings")
@require_auth(ANY)
def list_screenings(leagueId, volunteerId):
    get_league(leagueId)
    vol = get_volunteer(leagueId, volunteerId)
    limit, offset = parse_pagination(request.args)
    recs = _sorted(s for s in db.screenings.values() if s["volunteer_id"] == vol["id"])
    total = len(recs)
    return success_list([screening_view(s) for s in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/leagues/<leagueId>/volunteers/<volunteerId>/screenings/<screeningId>/adjudicate")
@require_auth(["DistrictAdministrator"])
def adjudicate_screening(leagueId, volunteerId, screeningId):
    league = get_league(leagueId)
    vol = get_volunteer(leagueId, volunteerId)
    scr = get_screening(vol["id"], screeningId)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in ("APPROVE", "DISQUALIFY"):
        raise err("ERR_INVALID_REQUEST", "action must be APPROVE or DISQUALIFY")
    # state (pr.5)
    if scr["status"] != "SUBMITTED":
        raise err("ERR_SCREENING_NOT_ADJUDICATABLE", "screening is not SUBMITTED")
    if action == "DISQUALIFY":
        scr["status"] = "DISQUALIFIED"
        touch(scr)
        if vol["status"] == "REGISTERED":
            vol["status"] = "DISQUALIFIED"
            touch(vol)
        return success_object(screening_view(scr))
    # APPROVE: severe-offense safety gate (pr.6) then window containment (pr.7)
    if scr["offense_category"] in SEVERE_OFFENSES:
        raise err("ERR_DISQUALIFYING_OFFENSE", "severe offense category cannot be approved")
    sy = league["season_year"]
    if not (scr["valid_from"] <= f"{sy}-03-01" and scr["valid_through"] >= f"{sy}-10-31"):
        raise err("ERR_SCREENING_WINDOW_INCOMPLETE",
                  "screening window does not contain the season window")
    scr["status"] = "CLEARED"
    touch(scr)
    if vol["status"] == "REGISTERED":
        vol["status"] = "CLEARED"
        touch(vol)
    return success_object(screening_view(scr))


# ---------------------------------------------------------------- insurance
@bp.post("/leagues/<leagueId>/insurance-certificates")
@require_auth(["DistrictAdministrator"])
def create_certificate(leagueId):
    get_league(leagueId)
    body = request.get_json(silent=True) or {}
    carrier_name = body.get("carrier_name")
    coverage_start = body.get("coverage_start")
    coverage_end = body.get("coverage_end")
    if not isinstance(carrier_name, str) or not carrier_name:
        raise err("ERR_INVALID_REQUEST", "carrier_name is required")
    if not isinstance(coverage_start, str) or not isinstance(coverage_end, str):
        raise err("ERR_INVALID_REQUEST", "coverage_start and coverage_end are required")
    try:
        cs = parse_date(coverage_start)
        ce = parse_date(coverage_end)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "dates must be YYYY-MM-DD")
    if ce < cs:
        raise err("ERR_INVALID_REQUEST", "coverage_end must be >= coverage_start")
    ts = now_ts()
    cert = {
        "id": new_id(),
        "league_id": leagueId,
        "carrier_name": carrier_name,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.certificates[cert["id"]] = cert
    return success_object(certificate_view(cert), 201)


@bp.get("/leagues/<leagueId>/insurance-certificates")
@require_auth(ANY)
def list_certificates(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    recs = _sorted(c for c in db.certificates.values() if c["league_id"] == leagueId)
    total = len(recs)
    return success_list([certificate_view(c) for c in recs[offset:offset + limit]],
                        limit, offset, total)
