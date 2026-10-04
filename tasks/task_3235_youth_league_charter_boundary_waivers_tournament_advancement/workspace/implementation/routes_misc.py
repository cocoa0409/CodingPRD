"""Cross-league filtered list endpoints, detail GETs, and the logical clock."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth, ANY
from response import success_object, success_list, parse_pagination
from serializers import (
    league_view, renewal_view, division_view, player_view, document_view,
    waiver_view, volunteer_view, screening_view, certificate_view, roster_view,
    entry_view, game_view, appearance_view, protest_view,
)
from services import clock_sweeps, parse_date

bp = Blueprint("misc", __name__)


def _sorted(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def _list(store, view, filters):
    limit, offset = parse_pagination(request.args)
    recs = list(store.values())
    for key, val in filters.items():
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    recs = _sorted(recs)
    total = len(recs)
    return success_list([view(r) for r in recs[offset:offset + limit]],
                        limit, offset, total)


def _detail(store, rid, view, error_id):
    rec = store.get(rid)
    if rec is None:
        raise err(error_id, f"{rid} not found")
    return success_object(view(rec))


# NOTE on route ordering: Flask matches concrete segments before converters
# when registered first; these literal-segment paths are registered before
# the /<leagueId> detail route in app.py to avoid ambiguity.

@bp.get("/leagues/charter-renewals")
@require_auth(ANY)
def x_renewals():
    return _list(db.renewals, renewal_view, {"league_id": request.args.get("league_id")})


@bp.get("/leagues/divisions")
@require_auth(ANY)
def x_divisions():
    return _list(db.divisions, division_view, {"league_id": request.args.get("league_id")})


@bp.get("/leagues/players")
@require_auth(ANY)
def x_players():
    return _list(db.players, player_view, {
        "league_id": request.args.get("league_id"),
        "division_id": request.args.get("division_id"),
    })


@bp.get("/leagues/eligibility-documents")
@require_auth(ANY)
def x_documents():
    return _list(db.documents, document_view, {"player_id": request.args.get("player_id")})


@bp.get("/leagues/boundary-waivers")
@require_auth(ANY)
def x_waivers():
    return _list(db.waivers, waiver_view, {
        "league_id": request.args.get("league_id"),
        "player_id": request.args.get("player_id"),
        "target_division_id": request.args.get("target_division_id"),
    })


@bp.get("/leagues/volunteers")
@require_auth(ANY)
def x_volunteers():
    return _list(db.volunteers, volunteer_view, {"league_id": request.args.get("league_id")})


@bp.get("/leagues/screenings")
@require_auth(ANY)
def x_screenings():
    return _list(db.screenings, screening_view,
                 {"volunteer_id": request.args.get("volunteer_id")})


@bp.get("/leagues/insurance-certificates")
@require_auth(ANY)
def x_certificates():
    return _list(db.certificates, certificate_view,
                 {"league_id": request.args.get("league_id")})


@bp.get("/leagues/all-star-rosters")
@require_auth(ANY)
def x_rosters():
    return _list(db.rosters, roster_view, {
        "league_id": request.args.get("league_id"),
        "division_id": request.args.get("division_id"),
    })


@bp.get("/leagues/tournament-entries")
@require_auth(ANY)
def x_entries():
    return _list(db.entries, entry_view, {
        "league_id": request.args.get("league_id"),
        "roster_id": request.args.get("roster_id"),
    })


@bp.get("/leagues/games")
@require_auth(ANY)
def x_games():
    return _list(db.games, game_view, {
        "entry_id": request.args.get("entry_id"),
        "opponent_entry_id": request.args.get("opponent_entry_id"),
    })


@bp.get("/leagues/pitching-appearances")
@require_auth(ANY)
def x_appearances():
    return _list(db.appearances, appearance_view, {
        "game_id": request.args.get("game_id"),
        "player_id": request.args.get("player_id"),
    })


@bp.get("/leagues/protests")
@require_auth(ANY)
def x_protests():
    return _list(db.protests, protest_view, {
        "game_id": request.args.get("game_id"),
        "target_player_id": request.args.get("target_player_id"),
    })


# ---------------------------------------------------------------- detail GETs
@bp.get("/leagues/leagues/<leagueId>")
@require_auth(ANY)
def d_league(leagueId):
    return _detail(db.leagues, leagueId, league_view, "ERR_LEAGUE_NOT_FOUND")


@bp.get("/leagues/charter-renewals/<renewalId>")
@require_auth(ANY)
def d_renewal(renewalId):
    return _detail(db.renewals, renewalId, renewal_view, "ERR_RENEWAL_NOT_FOUND")


@bp.get("/leagues/divisions/<divisionId>")
@require_auth(ANY)
def d_division(divisionId):
    return _detail(db.divisions, divisionId, division_view, "ERR_DIVISION_NOT_FOUND")


@bp.get("/leagues/players/<playerId>")
@require_auth(ANY)
def d_player(playerId):
    return _detail(db.players, playerId, player_view, "ERR_PLAYER_NOT_FOUND")


@bp.get("/leagues/eligibility-documents/<documentId>")
@require_auth(ANY)
def d_document(documentId):
    rec = db.documents.get(documentId)
    if rec is None:
        raise err("ERR_PLAYER_NOT_FOUND", f"{documentId} not found")
    return success_object(document_view(rec))


@bp.get("/leagues/boundary-waivers/<waiverId>")
@require_auth(ANY)
def d_waiver(waiverId):
    return _detail(db.waivers, waiverId, waiver_view, "ERR_WAIVER_NOT_FOUND")


@bp.get("/leagues/volunteers/<volunteerId>")
@require_auth(ANY)
def d_volunteer(volunteerId):
    return _detail(db.volunteers, volunteerId, volunteer_view, "ERR_VOLUNTEER_NOT_FOUND")


@bp.get("/leagues/screenings/<screeningId>")
@require_auth(ANY)
def d_screening(screeningId):
    return _detail(db.screenings, screeningId, screening_view, "ERR_SCREENING_NOT_FOUND")


@bp.get("/leagues/insurance-certificates/<certificateId>")
@require_auth(ANY)
def d_certificate(certificateId):
    return _detail(db.certificates, certificateId, certificate_view,
                   "ERR_LEAGUE_NOT_FOUND")


@bp.get("/leagues/all-star-rosters/<rosterId>")
@require_auth(ANY)
def d_roster(rosterId):
    return _detail(db.rosters, rosterId, roster_view, "ERR_ROSTER_NOT_FOUND")


@bp.get("/leagues/tournament-entries/<entryId>")
@require_auth(ANY)
def d_entry(entryId):
    return _detail(db.entries, entryId, entry_view, "ERR_ENTRY_NOT_FOUND")


@bp.get("/leagues/games/<gameId>")
@require_auth(ANY)
def d_game(gameId):
    return _detail(db.games, gameId, game_view, "ERR_GAME_NOT_FOUND")


@bp.get("/leagues/pitching-appearances/<appearanceId>")
@require_auth(ANY)
def d_appearance(appearanceId):
    rec = db.appearances.get(appearanceId)
    if rec is None:
        raise err("ERR_GAME_NOT_FOUND", f"{appearanceId} not found")
    return success_object(appearance_view(rec))


@bp.get("/leagues/protests/<protestId>")
@require_auth(ANY)
def d_protest(protestId):
    return _detail(db.protests, protestId, protest_view, "ERR_PROTEST_NOT_FOUND")


# ---------------------------------------------------------------- clock
@bp.post("/_clock/set_current_utc")
@require_auth(["DistrictAdministrator"])
def set_clock():
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or len(to_iso8601) < 10:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    try:
        parse_date(to_iso8601[:10])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    db.clock.set(to_iso8601)
    clock_sweeps(db.clock.date())
    return success_object({})
