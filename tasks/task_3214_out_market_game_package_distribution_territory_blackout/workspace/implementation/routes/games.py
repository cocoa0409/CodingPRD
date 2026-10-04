"""Games: schedule into a season week, list, get."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import err_season_structure, err_invalid_request
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import new_resource, get_or_404, find_slate, recompute_slate_count, week_window
from validate import body_json, req_string, req_int, req_datetime

bp = Blueprint("games", __name__)


@bp.post("/games")
@require_roles("LeagueOps", "PlatformAdmin")
def create_game(auth):
    body = body_json()
    season_id = req_string(body, "season_id")
    season = get_or_404(db.seasons, season_id)
    week_index = req_int(body, "week_index")
    away_team_code = req_string(body, "away_team_code")
    home_team_code = req_string(body, "home_team_code")
    kickoff_at = req_datetime(body, "kickoff_at")
    home_market_code = req_string(body, "home_market_code")

    if week_index < 1 or week_index > season["regular_season_weeks"]:
        raise err_season_structure("week_index out of season bounds")
    if away_team_code == home_team_code:
        raise err_season_structure("away_team_code must differ from home_team_code")
    if not any(m["code"] == home_market_code for m in db.markets.values()):
        raise err_season_structure("home_market_code must reference an existing market")
    kickoff = parse_iso(kickoff_at)
    wstart, wend = week_window(season, week_index)
    if kickoff < wstart or kickoff >= wend:
        raise err_season_structure("kickoff_at must fall inside the owning week's window")

    game = new_resource()
    game.update({
        "season_id": season_id,
        "week_index": week_index,
        "away_team_code": away_team_code,
        "home_team_code": home_team_code,
        "kickoff_at": kickoff_at,
        "home_market_code": home_market_code,
    })
    db.games[game["id"]] = game

    slate = find_slate(season_id, week_index)
    if slate is not None:
        recompute_slate_count(slate)
    return success(game, status=201)


@bp.get("/games")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent", "Subscriber", "VenueManager")
def list_games(auth):
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    week_index = request.args.get("week_index")
    home_market_code = request.args.get("home_market_code")
    items = sorted(db.games.values(), key=lambda r: r["created_at"])
    if season_id is not None:
        items = [g for g in items if g["season_id"] == season_id]
    if week_index is not None:
        try:
            wi = int(week_index)
        except (TypeError, ValueError):
            raise err_invalid_request("week_index must be an integer")
        items = [g for g in items if g["week_index"] == wi]
    if home_market_code is not None:
        items = [g for g in items if g["home_market_code"] == home_market_code]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/games/<gid>")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent", "Subscriber", "VenueManager")
def get_game(gid, auth):
    game = get_or_404(db.games, gid)
    return success(game)
