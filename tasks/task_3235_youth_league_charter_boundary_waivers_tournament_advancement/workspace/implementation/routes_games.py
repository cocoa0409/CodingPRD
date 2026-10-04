"""Tournament game, pitching-appearance, protest, and finalize routes."""
from flask import Blueprint, request

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import game_view, appearance_view, protest_view
from services import (
    ELIMINATION_LIMIT, PITCH_MAX, get_entry, get_game, get_protest,
    rest_days_for, compute_eligible_again_on, recompute_recorded_pitch_total,
    elimination_check, active_insurance, touch,
)

bp = Blueprint("games", __name__)


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def _require_active_entry(entry_id):
    entry = get_entry(entry_id)
    if entry["status"] != "ACTIVE":
        raise err("ERR_ENTRY_NOT_ACTIVE", "entry is not ACTIVE")
    return entry


# ---------------------------------------------------------------- games
@bp.post("/tournament-entries/<entryId>/games")
@require_auth(["TournamentDirector"])
def create_game(entryId):
    entry = _require_active_entry(entryId)
    body = request.get_json(silent=True) or {}
    opponent_entry_id = body.get("opponent_entry_id")
    if opponent_entry_id is not None:
        opp = db.entries.get(opponent_entry_id)
        if opp is None:
            raise err("ERR_ENTRY_NOT_FOUND", "opponent entry not found")
        if opp["status"] != "ACTIVE" or opp["level"] != entry["level"]:
            raise err("ERR_ENTRY_NOT_ACTIVE",
                      "opponent entry must be ACTIVE at the same level")
    ts = now_ts()
    game = {
        "id": new_id(),
        "entry_id": entryId,
        "opponent_entry_id": opponent_entry_id,
        "play_status": "SCHEDULED",
        "protest_status": "NONE",
        "game_date": None,
        "our_score": None,
        "opponent_score": None,
        "result": None,
        "recorded_pitch_total": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.games[game["id"]] = game
    return success_object(game_view(game), 201)


@bp.get("/tournament-entries/<entryId>/games")
@require_auth(ANY)
def list_games(entryId):
    get_entry(entryId)
    limit, offset = parse_pagination(request.args)
    opponent_entry_id = request.args.get("opponent_entry_id")
    recs = [g for g in db.games.values() if g["entry_id"] == entryId]
    if opponent_entry_id is not None:
        recs = [g for g in recs if g["opponent_entry_id"] == opponent_entry_id]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([game_view(g) for g in recs[offset:offset + limit]],
                        limit, offset, total)


# ---------------------------------------------------------------- appearances
@bp.post("/tournament-entries/<entryId>/games/<gameId>/pitching-appearances")
@require_auth(["OfficialScorer"])
def create_appearance(entryId, gameId):
    entry = _require_active_entry(entryId)
    game = get_game(entryId, gameId)
    if game["play_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_GAME_NOT_IN_PROGRESS", "game is not accepting appearances")
    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    pitches_thrown = body.get("pitches_thrown")
    player = db.players.get(player_id) if isinstance(player_id, str) else None
    if player is None:
        raise err("ERR_PLAYER_NOT_FOUND", "player not found")
    if not isinstance(pitches_thrown, int) or isinstance(pitches_thrown, bool) \
            or pitches_thrown < 1:
        raise err("ERR_INVALID_REQUEST", "pitches_thrown must be an integer >= 1")
    # safety (pr.6): pitch cap first
    div_code = None
    if player.get("division_id"):
        div = db.divisions.get(player["division_id"])
        div_code = div["division_code"] if div else None
    cap = PITCH_MAX.get(div_code, 95)
    if pitches_thrown > cap:
        raise err("ERR_PITCH_COUNT_EXCEEDED", "pitches_thrown exceeds division maximum")
    # safety: rest gate against the player's latest RECORDED appearance
    clock_d = db.clock.date()
    prior = [a for a in db.appearances.values()
             if a["player_id"] == player_id and a["status"] == "RECORDED"]
    if prior:
        prior.sort(key=lambda a: (a["appearance_date"], a["created_at"]))
        latest = prior[-1]
        if clock_d < latest["eligible_again_on"]:
            raise err("ERR_REST_REQUIREMENT_VIOLATION",
                      "clock date is before the player's eligible_again_on")
    # referential (pr.8): roster membership
    roster = db.rosters.get(entry["roster_id"])
    on_roster = roster is not None and any(
        s["player_id"] == player_id and s["status"] == "ACTIVE"
        for s in roster["selections"])
    if not on_roster:
        raise err("ERR_PLAYER_NOT_ON_ROSTER", "player holds no ACTIVE selection on the entry roster")
    # auto-start a SCHEDULED game
    if game["play_status"] == "SCHEDULED":
        game["play_status"] = "IN_PROGRESS"
        game["game_date"] = clock_d
    rest_days = rest_days_for(pitches_thrown)
    ts = now_ts()
    app = {
        "id": new_id(),
        "game_id": gameId,
        "player_id": player_id,
        "pitches_thrown": pitches_thrown,
        "official_pitches": None,
        "appearance_date": clock_d,
        "rest_days_required": rest_days,
        "eligible_again_on": compute_eligible_again_on(clock_d, rest_days),
        "status": "RECORDED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.appearances[app["id"]] = app
    recompute_recorded_pitch_total(game)
    touch(game)
    return success_object(appearance_view(app), 201)


@bp.get("/tournament-entries/<entryId>/games/<gameId>/pitching-appearances")
@require_auth(ANY)
def list_appearances(entryId, gameId):
    get_entry(entryId)
    get_game(entryId, gameId)
    limit, offset = parse_pagination(request.args)
    player_id = request.args.get("player_id")
    recs = [a for a in db.appearances.values() if a["game_id"] == gameId]
    if player_id is not None:
        recs = [a for a in recs if a["player_id"] == player_id]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([appearance_view(a) for a in recs[offset:offset + limit]],
                        limit, offset, total)


# ---------------------------------------------------------------- finalize
@bp.post("/tournament-entries/<entryId>/games/<gameId>/finalize")
@require_auth(["TournamentDirector"])
def finalize_game(entryId, gameId):
    entry = _require_active_entry(entryId)
    game = get_game(entryId, gameId)
    body = request.get_json(silent=True) or {}
    our_score = body.get("our_score")
    opponent_score = body.get("opponent_score")
    expected_game_version = body.get("expected_game_version")
    corrections = body.get("scorebook_corrections", [])
    # state (pr.5)
    if game["play_status"] != "IN_PROGRESS":
        raise err("ERR_GAME_NOT_IN_PROGRESS", "game is not IN_PROGRESS")
    for v, name in ((our_score, "our_score"), (opponent_score, "opponent_score")):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err("ERR_INVALID_REQUEST", f"{name} must be a non-negative integer")
    if not isinstance(expected_game_version, int) or isinstance(expected_game_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_game_version is required")
    if not isinstance(corrections, list):
        raise err("ERR_INVALID_REQUEST", "scorebook_corrections must be an array")
    # OCC
    if expected_game_version != game["version"]:
        raise err("ERR_STALE_VERSION", "game version has advanced")
    # insurance containment on the finalize clock date (pr.8 referential)
    clock_d = db.clock.date()
    has_ins = any(c["coverage_start"] <= clock_d <= c["coverage_end"]
                  for c in active_insurance(entry["league_id"]))
    if not has_ins:
        raise err("ERR_INSURANCE_NOT_ACTIVE",
                  "no ACTIVE insurance certificate contains the finalize date")
    # tie check
    if our_score == opponent_score:
        raise err("ERR_INVALID_REQUEST", "tied score is not allowed")
    # apply corrections first, then cap re-check on effective counts
    for c in corrections:
        if not isinstance(c, dict):
            raise err("ERR_INVALID_REQUEST", "invalid scorebook correction")
        aid = c.get("appearance_id")
        official = c.get("official_pitches")
        app = db.appearances.get(aid) if isinstance(aid, str) else None
        if app is None or app["game_id"] != gameId:
            raise err("ERR_INVALID_REQUEST", "correction references unknown appearance")
        if not isinstance(official, int) or isinstance(official, bool) or official < 1:
            raise err("ERR_INVALID_REQUEST", "official_pitches must be an integer >= 1")
        app["official_pitches"] = official
        app["rest_days_required"] = rest_days_for(official)
        app["eligible_again_on"] = compute_eligible_again_on(
            app["appearance_date"], app["rest_days_required"])
        touch(app)
    for a in db.appearances.values():
        if a["game_id"] != gameId or a["status"] != "RECORDED":
            continue
        effective = a["official_pitches"] if a["official_pitches"] is not None \
            else a["pitches_thrown"]
        player = db.players.get(a["player_id"])
        div_code = None
        if player and player.get("division_id"):
            div = db.divisions.get(player["division_id"])
            div_code = div["division_code"] if div else None
        cap = PITCH_MAX.get(div_code, 95)
        if effective > cap:
            raise err("ERR_PITCH_COUNT_EXCEEDED",
                      "effective pitch count exceeds division maximum")
    game["our_score"] = our_score
    game["opponent_score"] = opponent_score
    game["result"] = "WIN" if our_score > opponent_score else "LOSS"
    game["play_status"] = "FINAL"
    recompute_recorded_pitch_total(game)
    touch(game)
    if game["result"] == "LOSS":
        entry["losses_count"] += 1
        touch(entry)
        elimination_check(entry)
    return success_object(game_view(game))


# ---------------------------------------------------------------- protests
PROTEST_TYPES = {"RULE_INTERPRETATION", "ELIGIBILITY_CHALLENGE"}


@bp.post("/tournament-entries/<entryId>/games/<gameId>/protests")
@require_auth(["TournamentDirector"])
def create_protest(entryId, gameId):
    # Filing a protest is NOT gated on ACTIVE entry status: §3.7's list of
    # operations requiring an ACTIVE entry covers scheduling, appearances,
    # finalizing, and advancing — the protest path is precisely the mechanism
    # that can reverse an elimination, so it must remain reachable.
    get_entry(entryId)
    game = get_game(entryId, gameId)
    body = request.get_json(silent=True) or {}
    protest_type = body.get("protest_type")
    grounds = body.get("grounds")
    target_player_id = body.get("target_player_id")
    if protest_type not in PROTEST_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid protest_type")
    if not isinstance(grounds, str) or not grounds:
        raise err("ERR_INVALID_REQUEST", "grounds is required")
    if protest_type == "ELIGIBILITY_CHALLENGE":
        if not isinstance(target_player_id, str) or target_player_id not in db.players:
            raise err("ERR_PLAYER_NOT_FOUND", "target player not found")
    else:
        if target_player_id is not None:
            raise err("ERR_INVALID_REQUEST",
                      "target_player_id is forbidden for RULE_INTERPRETATION")
    # state (pr.5): game must be IN_PROGRESS or FINAL
    if game["play_status"] not in ("IN_PROGRESS", "FINAL"):
        raise err("ERR_GAME_NOT_IN_PROGRESS", "protests require IN_PROGRESS or FINAL game")
    if game["protest_status"] != "NONE":
        raise err("ERR_DUPLICATE_OPEN_PROTEST", "game already has a protest open or resolved")
    ts = now_ts()
    protest = {
        "id": new_id(),
        "game_id": gameId,
        "protest_type": protest_type,
        "target_player_id": target_player_id,
        "grounds": grounds,
        "status": "FILED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.protests[protest["id"]] = protest
    game["protest_status"] = "OPEN"
    touch(game)
    return success_object(protest_view(protest), 201)


@bp.get("/tournament-entries/<entryId>/games/<gameId>/protests")
@require_auth(ANY)
def list_protests(entryId, gameId):
    get_entry(entryId)
    get_game(entryId, gameId)
    limit, offset = parse_pagination(request.args)
    player_id = request.args.get("player_id")
    recs = [p for p in db.protests.values() if p["game_id"] == gameId]
    if player_id is not None:
        recs = [p for p in recs if p["target_player_id"] == player_id]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([protest_view(p) for p in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/tournament-entries/<entryId>/games/<gameId>/protests/<protestId>/resolve")
@require_auth(["TournamentDirector"])
def resolve_protest(entryId, gameId, protestId):
    entry = get_entry(entryId)
    game = get_game(entryId, gameId)
    protest = get_protest(gameId, protestId)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in ("UPHOLD", "OVERTURN", "WITHDRAW"):
        raise err("ERR_INVALID_REQUEST", "action must be UPHOLD, OVERTURN, or WITHDRAW")
    # state (pr.5)
    if protest["status"] != "FILED" or game["protest_status"] != "OPEN":
        raise err("ERR_PROTEST_NOT_OPEN", "protest is not resolvable")
    reopened = False
    if action == "UPHOLD" and protest["protest_type"] == "RULE_INTERPRETATION" \
            and game["play_status"] == "FINAL":
        voided_loss = (game["result"] == "LOSS")
        game["result"] = None
        game["play_status"] = "IN_PROGRESS"
        reopened = True
        if voided_loss:
            entry["losses_count"] = max(0, entry["losses_count"] - 1)
            if entry["status"] == "ELIMINATED":
                entry["status"] = "ACTIVE"
            touch(entry)
    elif action == "UPHOLD" and protest["protest_type"] == "ELIGIBILITY_CHALLENGE":
        target = protest["target_player_id"]
        for a in db.appearances.values():
            if (a["game_id"] == gameId and a["player_id"] == target
                    and a["status"] == "RECORDED"):
                a["status"] = "REVERSED"
                touch(a)
        recompute_recorded_pitch_total(game)
    protest["status"] = {"UPHOLD": "UPHELD", "OVERTURN": "OVERTURNED",
                         "WITHDRAW": "WITHDRAWN"}[action]
    touch(protest)
    game["protest_status"] = "NONE" if reopened else "RESOLVED"
    touch(game)
    return success_object(protest_view(protest))
