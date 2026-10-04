"""Boundary waiver routes."""
from flask import Blueprint, request

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import waiver_view
from services import get_league, get_waiver, parse_date, touch

bp = Blueprint("waivers", __name__)

WAIVER_TYPES = {"RESIDENCY_BOUNDARY", "PLAY_DOWN_SAFETY", "BIRTH_DATE_CUTOFF"}
TARGET_REQUIRED = {"PLAY_DOWN_SAFETY", "BIRTH_DATE_CUTOFF"}


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


@bp.post("/leagues/<leagueId>/boundary-waivers")
@require_auth(["LeagueAdministrator"])
def create_waiver(leagueId):
    league = get_league(leagueId)
    # charter gate (pr.4)
    if league["charter_status"] != "CHARTERED":
        raise err("ERR_LEAGUE_NOT_CHARTERED", "league is not CHARTERED")
    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    waiver_type = body.get("waiver_type")
    reason = body.get("reason")
    valid_from = body.get("valid_from")
    valid_until = body.get("valid_until")
    target_division_id = body.get("target_division_id")
    expected = body.get("expected_league_version")
    if not isinstance(player_id, str) or player_id not in db.players \
            or db.players[player_id]["league_id"] != leagueId:
        raise err("ERR_PLAYER_NOT_FOUND", "player not found in league")
    if waiver_type not in WAIVER_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid waiver_type")
    if not isinstance(reason, str) or not reason:
        raise err("ERR_INVALID_REQUEST", "reason is required")
    if not isinstance(valid_from, str) or not isinstance(valid_until, str):
        raise err("ERR_INVALID_REQUEST", "valid_from and valid_until are required")
    try:
        vf = parse_date(valid_from)
        vu = parse_date(valid_until)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "dates must be YYYY-MM-DD")
    if vu <= vf:
        raise err("ERR_INVALID_REQUEST", "valid_until must be strictly after valid_from")
    if waiver_type in TARGET_REQUIRED:
        if target_division_id is None:
            raise err("ERR_INVALID_REQUEST", "target_division_id is required for this waiver_type")
        div = db.divisions.get(target_division_id)
        if div is None or div["league_id"] != leagueId:
            raise err("ERR_DIVISION_NOT_FOUND", "target division not found in league")
    else:
        if target_division_id is not None:
            raise err("ERR_INVALID_REQUEST", "target_division_id is forbidden for RESIDENCY_BOUNDARY")
    # OCC: stale league version
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_league_version is required")
    if expected != league["version"]:
        raise err("ERR_STALE_VERSION", "league version has advanced")
    ts = now_ts()
    waiver = {
        "id": new_id(),
        "league_id": leagueId,
        "player_id": player_id,
        "waiver_type": waiver_type,
        "reason": reason,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "target_division_id": target_division_id,
        "status": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.waivers[waiver["id"]] = waiver
    touch(league)  # creation bumps league version by 1
    return success_object(waiver_view(waiver), 201)


@bp.get("/leagues/<leagueId>/boundary-waivers")
@require_auth(ANY)
def list_waivers(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    player_id = request.args.get("player_id")
    target_division_id = request.args.get("target_division_id")
    recs = [w for w in db.waivers.values() if w["league_id"] == leagueId]
    if player_id is not None:
        recs = [w for w in recs if w["player_id"] == player_id]
    if target_division_id is not None:
        recs = [w for w in recs if w["target_division_id"] == target_division_id]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([waiver_view(w) for w in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/leagues/<leagueId>/boundary-waivers/<waiverId>/decide")
@require_auth(["DistrictAdministrator"])
def decide_waiver(leagueId, waiverId):
    get_league(leagueId)
    waiver = get_waiver(leagueId, waiverId)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in ("APPROVE", "DENY", "REVOKE"):
        raise err("ERR_INVALID_REQUEST", "action must be APPROVE, DENY, or REVOKE")
    # state (pr.5)
    if action in ("APPROVE", "DENY"):
        if waiver["status"] != "PENDING":
            raise err("ERR_WAIVER_NOT_PENDING", "waiver is not PENDING")
    else:  # REVOKE
        if waiver["status"] != "APPROVED":
            raise err("ERR_WAIVER_NOT_PENDING", "waiver is not APPROVED")
    if action == "DENY":
        waiver["status"] = "DENIED"
        touch(waiver)
        return success_object(waiver_view(waiver))
    if action == "REVOKE":
        waiver["status"] = "REVOKED"
        touch(waiver)
        return success_object(waiver_view(waiver))
    # APPROVE: half-open overlap check per (player, waiver_type)
    a_from, a_until = waiver["valid_from"], waiver["valid_until"]
    for w in db.waivers.values():
        if (w["id"] != waiver["id"] and w["player_id"] == waiver["player_id"]
                and w["waiver_type"] == waiver["waiver_type"]
                and w["status"] == "APPROVED"):
            # intersect if a_from < w.valid_until and w.valid_from < a_until
            if a_from < w["valid_until"] and w["valid_from"] < a_until:
                raise err("ERR_WAIVER_OVERLAP", "overlapping APPROVED waiver window")
    waiver["status"] = "APPROVED"
    touch(waiver)
    if waiver["target_division_id"] is not None:
        player = db.players.get(waiver["player_id"])
        if player is not None:
            player["division_id"] = waiver["target_division_id"]
            touch(player)
    return success_object(waiver_view(waiver))
