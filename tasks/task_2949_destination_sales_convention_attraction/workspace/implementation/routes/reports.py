"""Board reports over a half-open reporting window (PRD 3.9)."""

from flask import Blueprint, request

import calc
import domain
import resolve
import serialize
from auth import BOARD_ANALYST, BUREAU_ADMIN, endpoint
from errors import ApiError
from response import created, list_response, object_response, pagination
from store import db, ordered, touch
from validation import body_json, query_enum, req_date, strictly_before

bp = Blueprint("reports", __name__)


@bp.route("/board-reports", methods=["POST"])
@endpoint(BOARD_ANALYST)
def create_report():
    body = body_json()
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    strictly_before(period_start, period_end, "period_start", "period_end")

    row = db.new_row()
    row.update({
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "published_at": None,
    })
    # every figure is computed once, at creation
    row.update(calc.board_rollup(period_start, period_end))
    db.board_reports[row["id"]] = row
    return created(serialize.board_report(row))


@bp.route("/board-reports/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, BOARD_ANALYST)
def get_report(row_id):
    return object_response(serialize.board_report(resolve.board_report(row_id)))


@bp.route("/board-reports", methods=["GET"])
@endpoint(BUREAU_ADMIN, BOARD_ANALYST)
def list_reports():
    status = query_enum(request.args, "status", domain.REPORT_STATUSES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.board_reports.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serialize.board_report, limit, offset)


@bp.route("/board-reports/<row_id>/publish", methods=["POST"])
@endpoint(BOARD_ANALYST)
def publish(row_id):
    report = resolve.board_report(row_id)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_BOARD_REPORT_PUBLISHED",
                       "A published report is frozen forever.")
    report["status"] = "PUBLISHED"
    report["published_at"] = db.clock
    touch(report)
    return object_response(serialize.board_report(report))
