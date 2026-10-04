"""Player, eligibility-document, and eligibility action routes."""
from datetime import timedelta
from flask import Blueprint, request

from db import db, new_id, now_ts
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import player_view, document_view
from services import (
    DIVISION_AGE_RANGES, get_league, get_player, league_divisions,
    compute_league_age, compute_participation_pct, parse_date, fmt_date,
    revoke_eligibility_cascade, touch,
)

bp = Blueprint("players", __name__)


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def _require_chartered(league):
    if league["charter_status"] != "CHARTERED":
        raise err("ERR_LEAGUE_NOT_CHARTERED", "league is not CHARTERED")


@bp.post("/leagues/<leagueId>/players")
@require_auth(["LeagueAdministrator"])
def create_player(leagueId):
    league = get_league(leagueId)
    _require_chartered(league)
    body = request.get_json(silent=True) or {}
    first_name = body.get("first_name")
    last_name = body.get("last_name")
    birth_date = body.get("birth_date")
    res_in = body.get("residence_within_boundary")
    sch_in = body.get("school_within_boundary")
    games_played = body.get("games_played")
    games_scheduled = body.get("games_scheduled")
    if not isinstance(first_name, str) or not first_name:
        raise err("ERR_INVALID_REQUEST", "first_name is required")
    if not isinstance(last_name, str) or not last_name:
        raise err("ERR_INVALID_REQUEST", "last_name is required")
    if not isinstance(birth_date, str):
        raise err("ERR_INVALID_REQUEST", "birth_date is required")
    try:
        parse_date(birth_date)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "birth_date must be YYYY-MM-DD")
    for v, name in ((res_in, "residence_within_boundary"),
                    (sch_in, "school_within_boundary")):
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", f"{name} must be boolean")
    for v, name in ((games_played, "games_played"), (games_scheduled, "games_scheduled")):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err("ERR_INVALID_REQUEST", f"{name} must be a non-negative integer")
    age = compute_league_age(birth_date, league["season_year"])
    division_id = None
    for d in league_divisions(leagueId):
        if d["min_league_age"] <= age <= d["max_league_age"]:
            division_id = d["id"]
            break
    pct = compute_participation_pct(games_played, games_scheduled)
    ts = now_ts()
    player = {
        "id": new_id(),
        "league_id": leagueId,
        "division_id": division_id,
        "first_name": first_name,
        "last_name": last_name,
        "birth_date": birth_date,
        "residence_within_boundary": res_in,
        "school_within_boundary": sch_in,
        "games_played": games_played,
        "games_scheduled": games_scheduled,
        "participation_pct": pct,
        "league_age": age,
        "eligibility_status": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.players[player["id"]] = player
    return success_object(player_view(player), 201)


@bp.get("/leagues/<leagueId>/players")
@require_auth(ANY)
def list_players(leagueId):
    get_league(leagueId)
    limit, offset = parse_pagination(request.args)
    division_id = request.args.get("division_id")
    eligibility_status = request.args.get("eligibility_status")
    recs = [p for p in db.players.values() if p["league_id"] == leagueId]
    if division_id is not None:
        recs = [p for p in recs if p["division_id"] == division_id]
    if eligibility_status is not None:
        recs = [p for p in recs if p["eligibility_status"] == eligibility_status]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([player_view(p) for p in recs[offset:offset + limit]],
                        limit, offset, total)


DOC_TYPES = {"BIRTH_CERTIFICATE", "RESIDENCE_PROOF", "SCHOOL_ENROLLMENT"}


@bp.post("/leagues/<leagueId>/players/<playerId>/eligibility-documents")
@require_auth(["LeagueAdministrator"])
def create_document(leagueId, playerId):
    get_league(leagueId)
    player = get_player(leagueId, playerId)
    body = request.get_json(silent=True) or {}
    doc_type = body.get("doc_type")
    issued_date = body.get("issued_date")
    if doc_type not in DOC_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid doc_type")
    if not isinstance(issued_date, str):
        raise err("ERR_INVALID_REQUEST", "issued_date is required")
    try:
        parse_date(issued_date)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "issued_date must be YYYY-MM-DD")
    doc = {
        "id": new_id(),
        "player_id": player["id"],
        "doc_type": doc_type,
        "issued_date": issued_date,
        "created_at": now_ts(),
        "_seq": db.next_seq(),
    }
    db.documents[doc["id"]] = doc
    return success_object(document_view(doc), 201)


@bp.get("/leagues/<leagueId>/players/<playerId>/eligibility-documents")
@require_auth(ANY)
def list_documents(leagueId, playerId):
    get_league(leagueId)
    player = get_player(leagueId, playerId)
    limit, offset = parse_pagination(request.args)
    recs = _sorted(d for d in db.documents.values() if d["player_id"] == player["id"])
    total = len(recs)
    return success_list([document_view(d) for d in recs[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/leagues/<leagueId>/players/<playerId>/verify-eligibility")
@require_auth(["LeagueAdministrator"])
def verify_eligibility(leagueId, playerId):
    league = get_league(leagueId)
    player = get_player(leagueId, playerId)
    # state (pr.5)
    if player["eligibility_status"] not in ("PENDING", "INELIGIBLE"):
        raise err("ERR_PLAYER_NOT_VERIFIABLE", "player is not PENDING or INELIGIBLE")
    clock_d = db.clock.date()
    # temporal (pr.7): registration window [season-01-01, season-04-30]
    sy = league["season_year"]
    if not (f"{sy}-01-01" <= clock_d <= f"{sy}-04-30"):
        raise err("ERR_REGISTRATION_WINDOW_CLOSED", "outside registration window")
    # referential (pr.8): documents
    docs = [d for d in db.documents.values() if d["player_id"] == player["id"]]
    has_birth = any(d["doc_type"] == "BIRTH_CERTIFICATE" for d in docs)
    if not player["residence_within_boundary"] and not player["school_within_boundary"]:
        # Waiver-based eligibility: no residency-basis document is required.
        basis_docs = []
        basis_required = False
    elif player["residence_within_boundary"]:
        basis_docs = [d for d in docs if d["doc_type"] == "RESIDENCE_PROOF"]
        basis_required = True
    else:
        basis_docs = [d for d in docs if d["doc_type"] == "SCHOOL_ENROLLMENT"]
        basis_required = True
    if not has_birth or (basis_required and not basis_docs):
        raise err("ERR_NO_ELIGIBILITY_DOCUMENT", "missing required eligibility document")
    # freshness: a fresh relied-upon document satisfies the rule even if a
    # stale document of the same type is also attached
    verify_d = parse_date(clock_d)
    if basis_docs and all(
            (verify_d - parse_date(d["issued_date"])) > timedelta(days=365)
            for d in basis_docs):
        raise err("ERR_DOCUMENT_EXPIRED", "document issued more than 365 days before verification")
    # boundary satisfaction
    boundary_ok = player["residence_within_boundary"] or player["school_within_boundary"]
    if not boundary_ok:
        for w in db.waivers.values():
            if (w["league_id"] == leagueId and w["player_id"] == player["id"]
                    and w["waiver_type"] == "RESIDENCY_BOUNDARY"
                    and w["status"] == "APPROVED"
                    and w["valid_from"] <= clock_d < w["valid_until"]):
                boundary_ok = True
                break
    if not boundary_ok:
        raise err("ERR_OUTSIDE_BOUNDARY", "no boundary basis satisfied")
    if player["division_id"] is None:
        raise err("ERR_AGE_DIVISION_MISMATCH", "player has no assigned division")
    player["eligibility_status"] = "ELIGIBLE"
    touch(player)
    return success_object(player_view(player))


@bp.post("/leagues/<leagueId>/players/<playerId>/revoke-eligibility")
@require_auth(["LeagueAdministrator"])
def revoke_eligibility(leagueId, playerId):
    get_league(leagueId)
    player = get_player(leagueId, playerId)
    if player["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_PLAYER_NOT_ELIGIBLE", "player is not ELIGIBLE")
    revoke_eligibility_cascade(player)
    return success_object(player_view(player))
