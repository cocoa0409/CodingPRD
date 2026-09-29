"""Pool reports and rules clarifications (PRD 3.9)."""

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_COMMUNICATIONS, endpoint
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("pool_reports", __name__)


@bp.route("/pool-reports", methods=["POST"])
@endpoint([ROLE_COMMUNICATIONS])
def draft_pool_report():
    """"A `supersedes_id` that names the drafting report itself, or a report
    belonging to a different game, is rejected with `ERR_INVALID_REQUEST`; one
    that names no existing report at all is `ERR_POOL_REPORT_NOT_FOUND`.\""""
    data = v.body()
    game_id = v.req_str(data, "game_id")
    play_grade_id = v.req_str(data, "play_grade_id")
    report_type = v.req_enum(data, "report_type", calc.REPORT_TYPES)
    text = v.req_str(data, "body", 1, 2000)
    supersedes_id = v.opt_str(data, "supersedes_id", 1, None, None)

    game = derive.get_game(game_id)
    grade = derive.get_play_grade(play_grade_id)
    target = None
    if supersedes_id is not None:
        target = derive.get_pool_report(supersedes_id)
        if target["game_id"] != game["id"]:
            fail(errors.ERR_INVALID_REQUEST,
                 "supersedes_id names a report belonging to a different game.")

    derive.require_program_open(derive.program_of_game(game))

    row = base_row()
    row.update({
        "game_id": game["id"],
        "play_grade_id": grade["id"],
        "report_type": report_type,
        "body": text,
        "supersedes_id": supersedes_id,
        "status": "DRAFT",
        "published_at": None,
    })
    db.pool_reports[row["id"]] = row
    return object_response(row, 201)


@bp.route("/pool-reports/<report_id>/publish", methods=["POST"])
@endpoint([ROLE_COMMUNICATIONS])
def publish_pool_report(report_id):
    """"Publication is legal only from `DRAFT` ... and only when the cited play
    grade has `grade_status` `FINAL` and an `appeal_state` that is not
    `APPEAL_PENDING`.\""""
    report = derive.get_pool_report(report_id)
    game = db.games.get(report["game_id"])
    derive.require_program_open(derive.program_of_game(game) if game else None)
    if report["status"] != "DRAFT":
        fail(errors.ERR_REPORT_STATE_INVALID,
             "Only a DRAFT report may be published.")
    grade = db.play_grades.get(report["play_grade_id"])
    if (grade is None or grade["grade_status"] != "FINAL"
            or grade["appeal_state"] == "APPEAL_PENDING"):
        fail(errors.ERR_CITED_GRADE_NOT_FINAL,
             "The cited play grade is not final and free of a pending appeal.")

    report["status"] = "PUBLISHED"
    report["published_at"] = now()
    touch(report)
    if report["supersedes_id"] is not None:
        target = db.pool_reports.get(report["supersedes_id"])
        if target is not None and target["status"] in ("DRAFT", "PUBLISHED"):
            target["status"] = "SUPERSEDED"
            touch(target)
    return object_response(report)


@bp.route("/pool-reports/<report_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_pool_report(report_id):
    return object_response(derive.get_pool_report(report_id))


@bp.route("/pool-reports", methods=["GET"])
@endpoint(ANY_ROLE)
def list_pool_reports():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.pool_reports)
    for name in ("game_id", "play_grade_id", "supersedes_id", "report_type",
                 "status"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
