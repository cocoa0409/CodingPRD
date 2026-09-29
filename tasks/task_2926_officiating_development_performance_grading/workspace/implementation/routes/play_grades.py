"""Play grades and the two state dimensions on one row (PRD 3.6)."""

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_GRADING_SUPERVISOR, caller_id, endpoint
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("play_grades", __name__)

WORKED_STATUSES = ("CONFIRMED", "COMPLETED")


@bp.route("/play-grades", methods=["POST"])
@endpoint([ROLE_GRADING_SUPERVISOR])
def create_play_grade():
    """"The triple of `game_id`, `official_id` and `play_ref` must be unique ...
    And the graded official must actually have worked the game -- they must hold
    an assignment on that game whose status is `CONFIRMED` or `COMPLETED`.\""""
    data = v.body()
    game_id = v.req_str(data, "game_id")
    official_id = v.req_str(data, "official_id")
    play_ref = v.req_str(data, "play_ref", 1, 40)
    call_category = v.req_enum(data, "call_category", calc.CALL_CATEGORIES)
    grade_code = v.req_enum(data, "grade_code", calc.GRADE_CODES)
    impact = v.req_enum(data, "impact", calc.IMPACTS)

    game = derive.get_game(game_id)
    official = derive.get_official(official_id)
    derive.require_program_open(derive.program_of_game(game))

    for existing in derive.rows_of(db.play_grades, game_id=game["id"],
                                   official_id=official["id"]):
        if existing["play_ref"] == play_ref:
            fail(errors.ERR_DUPLICATE_PLAY_GRADE,
                 "A grade already exists for this game, official and play.")

    worked = False
    for assignment in derive.assignments_of_official(official["id"]):
        if assignment["game_id"] == game["id"] and assignment["status"] in WORKED_STATUSES:
            worked = True
            break
    if not worked:
        fail(errors.ERR_ASSIGNMENT_STATE_INVALID,
             "The official held no CONFIRMED or COMPLETED assignment on this game.")

    row = base_row()
    row.update({
        "game_id": game["id"],
        "official_id": official["id"],
        "play_ref": play_ref,
        "call_category": call_category,
        "grade_code": grade_code,
        "impact": impact,
        "graded_by_user_id": caller_id(),
        "grade_status": "DRAFT",
        "appeal_state": "NOT_APPEALED",
        "posted_at": None,
        "error_points": calc.play_error_points(
            grade_code, impact, official["position"]),
    })
    db.play_grades[row["id"]] = row
    return object_response(row, 201)


@bp.route("/play-grades/<grade_id>/post", methods=["POST"])
@endpoint([ROLE_GRADING_SUPERVISOR])
def post_play_grade(grade_id):
    """"Posting is legal only from `grade_status` `DRAFT`, only while the program
    is `OPEN`, and only once the game has reached `PLAYED` or `FINALIZED`.\""""
    grade = derive.get_play_grade(grade_id)
    game = db.games.get(grade["game_id"])
    official = db.officials.get(grade["official_id"])
    derive.require_program_open(derive.program_of_grade(grade))
    if grade["grade_status"] != "DRAFT":
        fail(errors.ERR_GRADE_STATE_INVALID,
             "Only a DRAFT grade may be posted.")
    if game is None or game["status"] not in ("PLAYED", "FINALIZED"):
        fail(errors.ERR_GAME_STATE_INVALID,
             "A grade may only be posted once the game has been played.")

    grade["grade_status"] = "POSTED"
    grade["posted_at"] = now()
    touch(grade)
    if official is not None:
        derive.recompute_season_record(official, "PROVISIONAL")
    return object_response(grade)


@bp.route("/play-grades/<grade_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_play_grade(grade_id):
    return object_response(derive.get_play_grade(grade_id))


@bp.route("/play-grades", methods=["GET"])
@endpoint(ANY_ROLE)
def list_play_grades():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.play_grades)
    for name in ("game_id", "official_id", "grade_status", "appeal_state",
                 "grade_code"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
