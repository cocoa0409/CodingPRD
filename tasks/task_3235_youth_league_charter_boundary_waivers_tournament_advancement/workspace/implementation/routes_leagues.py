"""League, charter-renewal, and division routes."""
from flask import Blueprint, request

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import league_view, renewal_view, division_view
from services import (
    DIVISION_ORDER, DIVISION_AGE_RANGES, get_league, get_renewal, get_division,
    league_divisions, renewal_window_classification, charter_fee, touch,
    insurance_covers_dates,
)

bp = Blueprint("leagues", __name__)


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ---------------------------------------------------------------- leagues
@bp.post("/leagues")
@require_auth(["DistrictAdministrator"])
def create_league():
    body = request.get_json(silent=True) or {}
    league_name = body.get("league_name")
    region_code = body.get("region_code")
    season_year = body.get("season_year")
    if not isinstance(league_name, str) or not league_name:
        raise err("ERR_INVALID_REQUEST", "league_name is required")
    if not isinstance(region_code, str) or not region_code:
        raise err("ERR_INVALID_REQUEST", "region_code is required")
    if not isinstance(season_year, int) or isinstance(season_year, bool):
        raise err("ERR_INVALID_REQUEST", "season_year must be an integer")
    ts = now_ts()
    league = {
        "id": new_id(),
        "league_name": league_name,
        "region_code": region_code,
        "season_year": season_year,
        "charter_status": "PROVISIONAL",
        "total_team_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.leagues[league["id"]] = league
    for code in DIVISION_ORDER:
        lo, hi = DIVISION_AGE_RANGES[code]
        d = {
            "id": new_id(),
            "league_id": league["id"],
            "division_code": code,
            "min_league_age": lo,
            "max_league_age": hi,
            "team_count": 0,
            "status": "ACTIVE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.divisions[d["id"]] = d
    return success_object(league_view(league), 201)


@bp.get("/leagues")
@require_auth(ANY)
def list_leagues():
    limit, offset = parse_pagination(request.args)
    recs = _sorted(db.leagues.values())
    total = len(recs)
    page = recs[offset:offset + limit]
    return success_list([league_view(r) for r in page], limit, offset, total)


@bp.get("/leagues/<leagueId>")
@require_auth(ANY)
def get_league_route(leagueId):
    league = get_league(leagueId)
    return success_object(league_view(league))


# ---------------------------------------------------------------- charter renewals
@bp.post("/leagues/<leagueId>/charter-renewals")
@require_auth(["LeagueAdministrator"])
def create_renewal(leagueId):
    league = get_league(leagueId)
    body = request.get_json(silent=True) or {}
    season_year = body.get("season_year")
    if not isinstance(season_year, int) or isinstance(season_year, bool):
        raise err("ERR_INVALID_REQUEST", "season_year must be an integer")
    if season_year < league["season_year"]:
        raise err("ERR_INVALID_REQUEST", "season_year must be >= league season_year")
    for r in db.renewals.values():
        if (r["league_id"] == leagueId and r["season_year"] == season_year
                and r["status"] != "REJECTED"):
            raise err("ERR_INVALID_REQUEST",
                      "a non-REJECTED renewal already exists for this season_year")
    wc = renewal_window_classification(season_year, db.clock.date())
    fee = charter_fee(leagueId, wc)
    ts = now_ts()
    renewal = {
        "id": new_id(),
        "league_id": leagueId,
        "season_year": season_year,
        "window_classification": wc,
        "provisional_fee_cents": fee,
        "final_fee_cents": None,
        "late_fee_paid": False,
        "status": "SUBMITTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.renewals[renewal["id"]] = renewal
    return success_object(renewal_view(renewal), 201)


@bp.get("/leagues/<leagueId>/charter-renewals")
@require_auth(ANY)
def list_renewals(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    recs = _sorted(r for r in db.renewals.values() if r["league_id"] == leagueId)
    total = len(recs)
    return success_list([renewal_view(r) for r in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/leagues/<leagueId>/charter-renewals/<renewalId>/decide")
@require_auth(["DistrictAdministrator"])
def decide_renewal(leagueId, renewalId):
    league = get_league(leagueId)
    renewal = get_renewal(leagueId, renewalId)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in ("APPROVE", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "action must be APPROVE or REJECT")
    # state precondition (priority 5)
    if renewal["status"] != "SUBMITTED":
        raise err("ERR_RENEWAL_NOT_PENDING", "renewal is not SUBMITTED")
    if action == "REJECT":
        renewal["status"] = "REJECTED"
        touch(renewal)
        return success_object(renewal_view(renewal))
    # APPROVE path: insurance containment (referential, pr.8) then late fee (fiscal, pr.9)
    season_start = f"{renewal['season_year']}-03-01"
    season_end = f"{renewal['season_year']}-10-31"
    if not insurance_covers_dates(leagueId, season_start, season_end):
        raise err("ERR_INSURANCE_NOT_ACTIVE",
                  "no ACTIVE insurance certificate contains the season window")
    late_fee_paid = bool(body.get("late_fee_paid", False))
    if renewal["window_classification"] == "LATE" and not late_fee_paid:
        raise err("ERR_LATE_FEE_UNPAID", "LATE renewal requires late_fee_paid true")
    if renewal["window_classification"] == "ON_TIME":
        late_fee_paid = False
    renewal["late_fee_paid"] = late_fee_paid
    renewal["final_fee_cents"] = charter_fee(leagueId, renewal["window_classification"])
    renewal["status"] = "APPROVED"
    touch(renewal)
    # charter transition
    prior = league["charter_status"]
    league["charter_status"] = "CHARTERED"
    touch(league)
    if prior == "SUSPENDED":
        for d in league_divisions(leagueId):
            if d["status"] == "SUSPENDED":
                d["status"] = "ACTIVE"
                touch(d)
    return success_object(renewal_view(renewal))


# ---------------------------------------------------------------- divisions
@bp.get("/leagues/<leagueId>/divisions")
@require_auth(ANY)
def list_divisions(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    recs = league_divisions(leagueId)
    total = len(recs)
    return success_list([division_view(r) for r in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.patch("/leagues/<leagueId>/divisions/<divisionId>")
@require_auth(["LeagueAdministrator"])
def patch_division(leagueId, divisionId):
    league = get_league(leagueId)
    division = get_division(leagueId, divisionId)
    body = request.get_json(silent=True) or {}
    team_count = body.get("team_count")
    if not isinstance(team_count, int) or isinstance(team_count, bool) or team_count < 0:
        raise err("ERR_INVALID_REQUEST", "team_count must be a non-negative integer")
    division["team_count"] = team_count
    touch(division)
    league["total_team_count"] = sum(d["team_count"] for d in league_divisions(leagueId))
    touch(league)
    return success_object(division_view(division))
