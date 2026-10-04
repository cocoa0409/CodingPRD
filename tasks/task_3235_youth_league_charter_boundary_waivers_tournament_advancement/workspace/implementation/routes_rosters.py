"""All-star roster and tournament-entry routes."""
from decimal import Decimal
from flask import Blueprint, request

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import roster_view, entry_view
from services import (
    LEVEL_ORDER, PARTICIPATION_THRESHOLD, MIN_ROSTER_SIZE, MAX_ROSTER_SIZE,
    get_league, get_roster, recompute_roster_size, touch,
)

bp = Blueprint("rosters", __name__)


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def _require_chartered(league):
    if league["charter_status"] != "CHARTERED":
        raise err("ERR_LEAGUE_NOT_CHARTERED", "league is not CHARTERED")


# ---------------------------------------------------------------- rosters
@bp.post("/leagues/<leagueId>/all-star-rosters")
@require_auth(["LeagueAdministrator"])
def create_roster(leagueId):
    league = get_league(leagueId)
    _require_chartered(league)
    body = request.get_json(silent=True) or {}
    division_id = body.get("division_id")
    div = db.divisions.get(division_id) if isinstance(division_id, str) else None
    if div is None or div["league_id"] != leagueId:
        raise err("ERR_DIVISION_NOT_FOUND", "division not found in league")
    ts = now_ts()
    roster = {
        "id": new_id(),
        "league_id": leagueId,
        "division_id": division_id,
        "season_year": league["season_year"],
        "selections": [],
        "roster_size": 0,
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.rosters[roster["id"]] = roster
    return success_object(roster_view(roster), 201)


@bp.get("/leagues/<leagueId>/all-star-rosters")
@require_auth(ANY)
def list_rosters(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    division_id = request.args.get("division_id")
    recs = [r for r in db.rosters.values() if r["league_id"] == leagueId]
    if division_id is not None:
        recs = [r for r in recs if r["division_id"] == division_id]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([roster_view(r) for r in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/leagues/<leagueId>/all-star-rosters/<rosterId>/selections")
@require_auth(["LeagueAdministrator"])
def add_selection(leagueId, rosterId):
    league = get_league(leagueId)
    _require_chartered(league)
    roster = get_roster(leagueId, rosterId)
    # state (pr.5)
    if roster["status"] not in ("OPEN", "RECALLED"):
        raise err("ERR_ROSTER_NOT_OPEN", "roster is not OPEN or RECALLED")
    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    player = db.players.get(player_id) if isinstance(player_id, str) else None
    if player is None or player["league_id"] != leagueId:
        raise err("ERR_PLAYER_NOT_FOUND", "player not found in league")
    # pr.5 state check on player first
    if player["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_PLAYER_NOT_ELIGIBLE", "player is not ELIGIBLE")
    # pinned order: division match before capacity
    if player["division_id"] != roster["division_id"]:
        raise err("ERR_PLAYER_DIVISION_MISMATCH", "player division differs from roster division")
    if player["participation_pct"] < PARTICIPATION_THRESHOLD:
        raise err("ERR_PARTICIPATION_THRESHOLD_NOT_MET", "participation_pct below 60.00")
    recompute_roster_size(roster)
    if roster["roster_size"] + 1 > MAX_ROSTER_SIZE:
        raise err("ERR_ROSTER_ABOVE_MAXIMUM", "roster capacity exceeded")
    roster["selections"].append({
        "player_id": player_id,
        "selected_at": now_ts(),
        "status": "ACTIVE",
    })
    recompute_roster_size(roster)
    touch(roster)
    return success_object(roster_view(roster), 201)


@bp.post("/leagues/<leagueId>/all-star-rosters/<rosterId>/submit")
@require_auth(["LeagueAdministrator"])
def submit_roster(leagueId, rosterId):
    league = get_league(leagueId)
    _require_chartered(league)
    roster = get_roster(leagueId, rosterId)
    if roster["status"] not in ("OPEN", "RECALLED"):
        raise err("ERR_ROSTER_NOT_OPEN", "roster is not OPEN or RECALLED")
    recompute_roster_size(roster)
    if roster["roster_size"] < MIN_ROSTER_SIZE:
        raise err("ERR_ROSTER_BELOW_MINIMUM", "roster_size below minimum 3")
    for sel in roster["selections"]:
        if sel["status"] != "ACTIVE":
            continue
        player = db.players.get(sel["player_id"])
        if player is None or player["eligibility_status"] != "ELIGIBLE":
            raise err("ERR_PLAYER_NOT_ELIGIBLE", "selected player is not ELIGIBLE")
        if player["participation_pct"] < PARTICIPATION_THRESHOLD:
            raise err("ERR_PARTICIPATION_THRESHOLD_NOT_MET",
                      "selected player participation_pct below 60.00")
    roster["status"] = "SUBMITTED"
    touch(roster)
    return success_object(roster_view(roster))


# ---------------------------------------------------------------- entries
@bp.post("/leagues/<leagueId>/tournament-entries")
@require_auth(["TournamentDirector"])
def create_entry(leagueId):
    league = get_league(leagueId)
    _require_chartered(league)
    body = request.get_json(silent=True) or {}
    roster_id = body.get("roster_id")
    level = body.get("level")
    if level not in LEVEL_ORDER:
        raise err("ERR_INVALID_REQUEST", "invalid level")
    roster = get_roster(leagueId, roster_id) if isinstance(roster_id, str) else None
    if roster is None:
        raise err("ERR_ROSTER_NOT_FOUND", "roster not found in league")
    if level != "DISTRICT":
        preceding = LEVEL_ORDER[LEVEL_ORDER.index(level) - 1]
        ok = any(e for e in db.entries.values()
                 if e["league_id"] == leagueId and e["level"] == preceding
                 and e["status"] == "ADVANCED")
        if not ok:
            raise err("ERR_ADVANCEMENT_PREREQUISITE_NOT_MET",
                      "no ADVANCED entry at the preceding level")
    if roster["status"] != "SUBMITTED":
        raise err("ERR_ROSTER_NOT_SUBMITTED", "roster is not SUBMITTED")
    fmt = "DOUBLE_ELIMINATION" if level in ("DISTRICT", "SECTIONAL") else "SINGLE_ELIMINATION"
    ts = now_ts()
    entry = {
        "id": new_id(),
        "league_id": leagueId,
        "roster_id": roster_id,
        "level": level,
        "elimination_format": fmt,
        "losses_count": 0,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.entries[entry["id"]] = entry
    roster["status"] = "LOCKED"
    touch(roster)
    return success_object(entry_view(entry), 201)


@bp.get("/leagues/<leagueId>/tournament-entries")
@require_auth(ANY)
def list_entries(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    roster_id = request.args.get("roster_id")
    recs = [e for e in db.entries.values() if e["league_id"] == leagueId]
    if roster_id is not None:
        recs = [e for e in recs if e["roster_id"] == roster_id]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([entry_view(e) for e in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/tournament-entries/<entryId>/advance")
@require_auth(["TournamentDirector"])
def advance_entry(entryId):
    entry = db.entries.get(entryId)
    if entry is None:
        raise err("ERR_ENTRY_NOT_FOUND", "entry not found")
    if entry["status"] != "ACTIVE":
        raise err("ERR_ENTRY_NOT_ACTIVE", "entry is not ACTIVE")
    if entry["level"] == "REGIONAL":
        raise err("ERR_ALREADY_HIGHEST_LEVEL", "REGIONAL entries cannot advance")
    games = [g for g in db.games.values() if g["entry_id"] == entryId]
    for g in games:
        if g["protest_status"] == "OPEN":
            raise err("ERR_PROTEST_NOT_OPEN", "an open protest blocks advancement")
    has_win = any(g["play_status"] == "FINAL" and g["result"] == "WIN" for g in games)
    limit = 1 if entry["elimination_format"] == "SINGLE_ELIMINATION" else 2
    if not has_win or entry["losses_count"] >= limit:
        raise err("ERR_ADVANCEMENT_PREREQUISITE_NOT_MET",
                  "advance requires a FINAL WIN and losses below the elimination limit")
    entry["status"] = "ADVANCED"
    touch(entry)
    return success_object(entry_view(entry))
