"""Crew assignments: occupancy, rotation and the crew slot (PRD 2.8, 3.4)."""

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_SCHEDULER, endpoint
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("assignments", __name__)

OCCUPYING_STATUSES = ("PROPOSED", "CONFIRMED", "COMPLETED")


def _team_exposures(official_id, program_id, team_code):
    """"For each of the two team codes, the server counts the official's
    assignments in `PROPOSED`, `CONFIRMED` or `COMPLETED` status whose game
    belongs to the same season program and whose game names that team as either
    home or away side.\""""
    count = 0
    for assignment in derive.assignments_of_official(official_id):
        if assignment["status"] not in OCCUPYING_STATUSES:
            continue
        game = db.games.get(assignment["game_id"])
        if game is None or game["season_program_id"] != program_id:
            continue
        if team_code in (game["home_team_code"], game["away_team_code"]):
            count += 1
    return count


@bp.route("/crew-assignments", methods=["POST"])
@endpoint([ROLE_SCHEDULER])
def propose_assignment():
    data = v.body()
    game_id = v.req_str(data, "game_id")
    official_id = v.req_str(data, "official_id")
    position = v.req_enum(data, "position", calc.POSITIONS)
    expected_game_version = v.req_int(data, "expected_game_version", minimum=0)

    # Step 4: body identifiers in the order the endpoint declares its inputs.
    game = derive.get_game(game_id)
    official = derive.get_official(official_id)

    program = derive.program_of_game(game)
    derive.require_program_open(program)

    if game["status"] != "SCHEDULED":
        fail(errors.ERR_GAME_STATE_INVALID,
             "An official may only be proposed on a SCHEDULED game.")

    if expected_game_version != game["version"]:
        fail(errors.ERR_STALE_GAME_VERSION,
             "expected_game_version %d does not match the game's current "
             "version %d." % (expected_game_version, game["version"]))

    occupied_from, occupied_until = calc.occupancy_window(
        game["kickoff_utc"], program["travel_lead_hours"],
        program["min_rest_hours_between_games"])

    # Step 10 -- fatigue safety outranks every rule below it.
    for existing in derive.assignments_of_official(official["id"]):
        if existing["status"] not in OCCUPYING_STATUSES:
            continue
        if calc.windows_conflict(occupied_from, occupied_until,
                                 existing["occupied_from_utc"],
                                 existing["occupied_until_utc"]):
            fail(errors.ERR_OFFICIAL_WINDOW_CONFLICT,
                 "The official's occupancy window overlaps assignment '%s'."
                 % existing["id"])

    if official["status"] != "ACTIVE":
        fail(errors.ERR_OFFICIAL_NOT_ACTIVE, "The official is not ACTIVE.")
    if not official["preseason_cleared"]:
        fail(errors.ERR_PRESEASON_NOT_CLEARED,
             "The official is not preseason cleared.")
    if official["affiliated_team_code"] is not None and official[
            "affiliated_team_code"] in (game["home_team_code"],
                                        game["away_team_code"]):
        fail(errors.ERR_TEAM_CONFLICT_OF_INTEREST,
             "The official has a declared conflict with a team in this game.")
    cap = program["max_team_exposures_per_season"]
    for team_code in (game["home_team_code"], game["away_team_code"]):
        if _team_exposures(official["id"], program["id"], team_code) >= cap:
            fail(errors.ERR_TEAM_ROTATION_LIMIT,
                 "The official has reached the season exposure cap against %s."
                 % team_code)

    superseded = None
    for existing in derive.assignments_of_game(game["id"]):
        if existing["position"] != position:
            continue
        if existing["status"] == "CONFIRMED":
            fail(errors.ERR_POSITION_ALREADY_CONFIRMED,
                 "Position %s is already confirmed on this game." % position)
        if existing["status"] == "PROPOSED":
            superseded = existing

    # "If a merely PROPOSED assignment occupies it, the incoming proposal wins."
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        superseded["released_at"] = now()
        touch(superseded)
        prior_official = db.officials.get(superseded["official_id"])
        if prior_official is not None:
            prior_official["open_assignment_count"] = max(
                0, prior_official["open_assignment_count"] - 1)
            touch(prior_official)

    row = base_row()
    row.update({
        "game_id": game["id"],
        "official_id": official["id"],
        "position": position,
        "status": "PROPOSED",
        "occupied_from_utc": occupied_from,
        "occupied_until_utc": occupied_until,
        "released_at": None,
    })
    db.assignments[row["id"]] = row

    official["open_assignment_count"] = official["open_assignment_count"] + 1
    touch(official)
    derive.refresh_game_derived(game, "PROJECTED")
    touch(game)
    return object_response(row, 201)


@bp.route("/crew-assignments/<assignment_id>/confirm", methods=["POST"])
@endpoint([ROLE_SCHEDULER])
def confirm_assignment(assignment_id):
    """"legal only from `PROPOSED`, only while the game is `SCHEDULED` and the
    program is `OPEN`, and only when the official is still `ACTIVE` and still
    `preseason_cleared`.\""""
    assignment = derive.get_assignment(assignment_id)
    game = db.games.get(assignment["game_id"])
    official = db.officials.get(assignment["official_id"])
    derive.require_program_open(derive.program_of_game(game))
    if assignment["status"] != "PROPOSED":
        fail(errors.ERR_ASSIGNMENT_STATE_INVALID,
             "Only a PROPOSED assignment may be confirmed.")
    if game["status"] != "SCHEDULED":
        fail(errors.ERR_GAME_STATE_INVALID,
             "An assignment may only be confirmed while the game is SCHEDULED.")
    if official["status"] != "ACTIVE":
        fail(errors.ERR_OFFICIAL_NOT_ACTIVE, "The official is not ACTIVE.")
    if not official["preseason_cleared"]:
        fail(errors.ERR_PRESEASON_NOT_CLEARED,
             "The official is not preseason cleared.")

    assignment["status"] = "CONFIRMED"
    touch(assignment)
    derive.refresh_game_derived(game, "PROJECTED")
    touch(game)
    return object_response(assignment)


@bp.route("/crew-assignments/<assignment_id>/withdraw", methods=["POST"])
@endpoint([ROLE_SCHEDULER])
def withdraw_assignment(assignment_id):
    """"legal from either `PROPOSED` or `CONFIRMED`, and only while the game is
    still `SCHEDULED`.\""""
    data = v.body()
    v.opt_str(data, "reason", 1, None, None)

    assignment = derive.get_assignment(assignment_id)
    game = db.games.get(assignment["game_id"])
    official = db.officials.get(assignment["official_id"])
    derive.require_program_open(derive.program_of_game(game))
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        fail(errors.ERR_ASSIGNMENT_STATE_INVALID,
             "Only a PROPOSED or CONFIRMED assignment may be withdrawn.")
    if game["status"] != "SCHEDULED":
        fail(errors.ERR_GAME_STATE_INVALID,
             "An assignment may only be withdrawn while the game is SCHEDULED.")

    assignment["status"] = "WITHDRAWN"
    assignment["released_at"] = now()
    touch(assignment)
    if official is not None:
        official["open_assignment_count"] = max(
            0, official["open_assignment_count"] - 1)
        touch(official)
    derive.refresh_game_derived(game, "PROJECTED")
    touch(game)
    return object_response(assignment)


@bp.route("/crew-assignments/<assignment_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_assignment(assignment_id):
    return object_response(derive.get_assignment(assignment_id))


@bp.route("/crew-assignments", methods=["GET"])
@endpoint(ANY_ROLE)
def list_assignments():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.assignments)
    for name in ("game_id", "official_id", "status", "position"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
