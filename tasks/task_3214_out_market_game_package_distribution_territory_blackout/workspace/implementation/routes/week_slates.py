"""Week slates: create, list, get, selections, finalize, reopen, lock (OCC)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err_season_structure, err_already_terminal, err_invalid_state,
    err_stale_slate_version, err_game_week_mismatch,
    err_national_selection_conflict, err_slate_locked, err_invalid_request,
)
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, touch, get_or_404, find_slate, recompute_slate_count,
    package_game_ids, sweep_national_selection,
)
from validate import body_json, req_string, req_int, req_enum, opt_field

bp = Blueprint("week_slates", __name__)


def _package_game_count(season_id, week_index, national_ids):
    games = [
        g for g in db.games.values()
        if g["season_id"] == season_id and g["week_index"] == week_index
    ]
    return len([g for g in games if g["id"] not in set(national_ids)])


@bp.post("/week-slates")
@require_roles("LeagueOps", "PlatformAdmin")
def create_week_slate(auth):
    body = body_json()
    season_id = req_string(body, "season_id")
    season = get_or_404(db.seasons, season_id)
    week_index = req_int(body, "week_index")
    if week_index < 1 or week_index > season["regular_season_weeks"]:
        raise err_season_structure("week_index out of season bounds")
    if find_slate(season_id, week_index) is not None:
        raise err_season_structure("WeekSlate already exists for (season, week_index)")

    slate = new_resource()
    slate.update({
        "season_id": season_id,
        "week_index": week_index,
        "slate_status": "PRELIMINARY",
        "national_game_ids": [],
        "finalized_game_ids": [],
        "package_game_count": _package_game_count(season_id, week_index, []),
        "finalized_at": None,
    })
    db.week_slates[slate["id"]] = slate
    return success(slate, status=201)


@bp.get("/week-slates")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent")
def list_week_slates(auth):
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    slate_status = request.args.get("slate_status")
    items = sorted(db.week_slates.values(), key=lambda r: r["created_at"])
    if season_id is not None:
        items = [s for s in items if s["season_id"] == season_id]
    if slate_status is not None:
        items = [s for s in items if s["slate_status"] == slate_status]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/week-slates/<sid>")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent")
def get_week_slate(sid, auth):
    slate = get_or_404(db.week_slates, sid)
    return success(slate)


def _check_occ(body, slate):
    expected = opt_field(body, "expected_slate_version")
    if expected is not None and expected != slate["version"]:
        raise err_stale_slate_version()


@bp.post("/week-slates/<sid>/selections")
@require_roles("LeagueOps")
def slate_selections(sid, auth):
    slate = get_or_404(db.week_slates, sid)
    if slate["slate_status"] == "LOCKED":
        raise err_slate_locked()
    if slate["slate_status"] not in ("PRELIMINARY", "FINALIZED"):
        raise err_invalid_state()
    body = body_json()
    _check_occ(body, slate)
    game_id = req_string(body, "game_id")
    action = req_enum(body, "action", {"add", "remove", "ADD", "REMOVE"}).lower()
    game = db.games.get(game_id)
    if game is None or game["season_id"] != slate["season_id"] or game["week_index"] != slate["week_index"]:
        raise err_game_week_mismatch()

    if action == "add":
        if game_id in slate["national_game_ids"]:
            raise err_national_selection_conflict("Game already in national_game_ids")
        slate["national_game_ids"].append(game_id)
        # order by game's created_at
        slate["national_game_ids"].sort(key=lambda gid: db.games[gid]["created_at"])
    else:
        if game_id not in slate["national_game_ids"]:
            raise err_national_selection_conflict("Game not in national_game_ids")
        slate["national_game_ids"].remove(game_id)

    sweep_national_selection(slate, game_id, action)
    if slate["slate_status"] in ("FINALIZED", "LOCKED"):
        slate["finalized_game_ids"] = package_game_ids(slate)
    recompute_slate_count(slate)
    touch(slate)
    return success(slate)


@bp.post("/week-slates/<sid>/finalize")
@require_roles("LeagueOps")
def finalize_slate(sid, auth):
    slate = get_or_404(db.week_slates, sid)
    if slate["slate_status"] == "LOCKED":
        raise err_already_terminal()
    if slate["slate_status"] != "PRELIMINARY":
        raise err_invalid_state()
    body = body_json()
    _check_occ(body, slate)
    slate["finalized_game_ids"] = package_game_ids(slate)
    slate["finalized_at"] = db.clock.now_iso()
    slate["slate_status"] = "FINALIZED"
    slate["package_game_count"] = len(slate["finalized_game_ids"])
    touch(slate)
    return success(slate)


@bp.post("/week-slates/<sid>/reopen")
@require_roles("LeagueOps")
def reopen_slate(sid, auth):
    slate = get_or_404(db.week_slates, sid)
    if slate["slate_status"] == "LOCKED":
        raise err_slate_locked()
    if slate["slate_status"] != "FINALIZED":
        raise err_invalid_state()
    slate["finalized_game_ids"] = []
    slate["slate_status"] = "PRELIMINARY"
    recompute_slate_count(slate)
    touch(slate)
    return success(slate)


@bp.post("/week-slates/<sid>/lock")
@require_roles("LeagueOps")
def lock_slate(sid, auth):
    slate = get_or_404(db.week_slates, sid)
    if slate["slate_status"] == "LOCKED":
        raise err_already_terminal()
    if slate["slate_status"] != "FINALIZED":
        raise err_invalid_state()
    games = [
        g for g in db.games.values()
        if g["season_id"] == slate["season_id"] and g["week_index"] == slate["week_index"]
    ]
    if not games:
        raise err_invalid_state("Cannot lock a slate with no games")
    earliest = min(parse_iso(g["kickoff_at"]) for g in games)
    if db.clock.now() < earliest:
        raise err_invalid_state("Cannot lock before the week's first kickoff")
    slate["slate_status"] = "LOCKED"
    touch(slate)
    return success(slate)
