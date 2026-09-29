"""Games: scheduling, kickoff, end of play and finalization (PRD 3.4-3.6, 3.9)."""

from decimal import Decimal

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_DIRECTOR, endpoint
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("games", __name__)


@bp.route("/games", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def schedule_game():
    """"A scheduled game starts at `status` `SCHEDULED`, `crew_posture`
    `UNDERSTAFFED`, `confirmed_crew_count` 0, `crew_strength_index` 0.00 and
    `crew_strength_variant` `PROJECTED`.\""""
    data = v.body()
    program_id = v.req_str(data, "season_program_id")
    home_team_code = v.req_team_code(data, "home_team_code")
    away_team_code = v.req_team_code(data, "away_team_code")
    venue_market_code = v.req_team_code(data, "venue_market_code")
    kickoff_utc = v.req_datetime(data, "kickoff_utc")
    if home_team_code == away_team_code:
        fail(errors.ERR_INVALID_REQUEST,
             "home_team_code and away_team_code must differ.")

    program = derive.get_program(program_id)
    derive.require_program_open(program)

    row = base_row()
    row.update({
        "season_program_id": program_id,
        "home_team_code": home_team_code,
        "away_team_code": away_team_code,
        "venue_market_code": venue_market_code,
        "kickoff_utc": kickoff_utc,
        "status": "SCHEDULED",
        "crew_posture": "UNDERSTAFFED",
        "confirmed_crew_count": 0,
        "crew_strength_index": Decimal("0.00"),
        "crew_strength_variant": "PROJECTED",
    })
    db.games[row["id"]] = row
    return object_response(row, 201)


@bp.route("/games/<game_id>/kickoff", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def kickoff_game(game_id):
    """"Kickoff ... is legal only from `SCHEDULED`, only while the program is
    `OPEN`, and only when the game's `crew_posture` is `STAFFED`; a short crew is
    refused with `ERR_CREW_NOT_STAFFED`.\""""
    game = derive.get_game(game_id)
    derive.require_program_open(derive.program_of_game(game))
    if game["status"] != "SCHEDULED":
        fail(errors.ERR_GAME_STATE_INVALID,
             "A game may only kick off from SCHEDULED.")
    if derive.derive_crew_posture(game) != "STAFFED":
        fail(errors.ERR_CREW_NOT_STAFFED, "The game's crew is not STAFFED.")

    game["status"] = "IN_PROGRESS"
    # "freezes crew_posture at LOCKED, recomputes crew_strength_index one last
    # time with the PROJECTED variant and writes crew_strength_variant as
    # PROJECTED".
    derive.refresh_game_derived(game, "PROJECTED")
    touch(game)
    return object_response(game)


@bp.route("/games/<game_id>/mark-played", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def mark_game_played(game_id):
    """"moves the game `IN_PROGRESS -> PLAYED` while sweeping two collections"
    -- the confirmed crew completes and every review still `INITIATED` expires,
    both in `created_at` ascending order."""
    game = derive.get_game(game_id)
    program = derive.program_of_game(game)
    derive.require_program_open(program)
    if game["status"] != "IN_PROGRESS":
        fail(errors.ERR_GAME_STATE_INVALID,
             "Play may only be ended on a game that is IN_PROGRESS.")

    game["status"] = "PLAYED"
    for assignment in derive.assignments_of_game(game["id"]):
        if assignment["status"] != "CONFIRMED":
            continue
        assignment["status"] = "COMPLETED"
        touch(assignment)
        official = db.officials.get(assignment["official_id"])
        if official is not None:
            official["open_assignment_count"] = max(
                0, official["open_assignment_count"] - 1)
            touch(official)
    # confirmed_crew_count is by definition the number of CONFIRMED assignments
    # (PRD 2.10), and the completed crew has left that set.
    game["confirmed_crew_count"] = len([
        a for a in derive.assignments_of_game(game["id"])
        if a["status"] == "CONFIRMED"])

    for review in derive.rows_of(db.replay_reviews, game_id=game["id"]):
        if review["status"] != "INITIATED":
            continue
        review["status"] = "EXPIRED"
        review["decision"] = None
        review["elapsed_seconds"] = calc.elapsed_whole_seconds(
            review["window_open_utc"], now())
        touch(review)
        station = db.replay_stations.get(review["station_id"])
        if station is not None:
            station["active_review_count"] = max(
                0, station["active_review_count"] - 1)
            touch(station)

    touch(game)
    return object_response(game)


@bp.route("/games/<game_id>/finalize", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def finalize_game(game_id):
    """"Every play grade on that game whose `grade_status` is `POSTED` and whose
    `appeal_state` is not `APPEAL_PENDING` moves `POSTED -> FINAL`, processed in
    `created_at` ascending order ... The game's `crew_strength_index` is
    recomputed with the `REALIZED` variant ... And the season record of every
    official graded on that game is recomputed with the `PROVISIONAL` accuracy
    variant.\""""
    game = derive.get_game(game_id)
    derive.require_program_open(derive.program_of_game(game))
    if game["status"] != "PLAYED":
        fail(errors.ERR_GAME_STATE_INVALID,
             "A game may only be finalized from PLAYED.")

    game["status"] = "FINALIZED"
    graded_official_ids = []
    for grade in derive.rows_of(db.play_grades, game_id=game["id"]):
        if grade["official_id"] not in graded_official_ids:
            graded_official_ids.append(grade["official_id"])
        if grade["grade_status"] != "POSTED":
            continue
        if grade["appeal_state"] == "APPEAL_PENDING":
            continue
        grade["grade_status"] = "FINAL"
        touch(grade)

    derive.refresh_game_derived(game, "REALIZED")
    touch(game)

    for official_id in graded_official_ids:
        official = db.officials.get(official_id)
        if official is not None:
            derive.recompute_season_record(official, "PROVISIONAL")
    return object_response(game)


@bp.route("/games/<game_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_game(game_id):
    return object_response(derive.get_game(game_id))


@bp.route("/games", methods=["GET"])
@endpoint(ANY_ROLE)
def list_games():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.games)
    for name in ("season_program_id", "status", "crew_posture",
                 "home_team_code", "away_team_code"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
