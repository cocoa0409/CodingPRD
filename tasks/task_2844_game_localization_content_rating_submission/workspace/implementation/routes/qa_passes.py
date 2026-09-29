"""QA pass endpoints (PRD SS3.6)."""
from decimal import Decimal

from flask import Blueprint

from constants import (
    ALL_ROLES,
    DEFECT_DENSITY_CEILING,
    PASS_TYPES,
    ROLE_LQA_TESTER,
)
from db import base_row, db, fetch, insert, rows, touch
from derive import plan_passes, recompute_pass_density
from errors import ApiError
from middleware import endpoint, require_distinct_actor, user_id
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import nk_qa_pass, qa_pass_out
from validation import json_body, req_enum, req_id, req_int

bp = Blueprint("qa_passes", __name__)

TESTERS = [ROLE_LQA_TESTER]


@bp.route("/qa-passes", methods=["POST"])
@endpoint(TESTERS)
def create_qa_pass():
    body = json_body()
    market_plan_id = req_id(body, "market_plan_id")
    pass_type = req_enum(body, "pass_type", PASS_TYPES)
    inspected_unit_count = req_int(body, "inspected_unit_count", 1)

    plan = fetch("market_plans", market_plan_id)

    siblings = plan_passes(market_plan_id)
    same_type = [p for p in siblings if p["pass_type"] == pass_type]

    # rung 10 -- at most one OPEN pass of the requested type per plan
    if any(p["status"] == "OPEN" for p in same_type):
        raise ApiError("ERR_OPEN_QA_PASS_EXISTS")

    # rung 12 -- the plan must be under localisation or in LQA
    if plan["status"] not in ("IN_LOCALIZATION", "LQA"):
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The market plan must be IN_LOCALIZATION or LQA",
        )

    row = base_row()
    row.update({
        "market_plan_id": market_plan_id,
        "pass_type": pass_type,
        "pass_index": len(same_type) + 1,
        "inspected_unit_count": inspected_unit_count,
        "opened_by_user_id": user_id(),
        "status": "OPEN",
        "reopen_count": 0,
        "weighted_defect_points": 0,
        "defect_density": Decimal("0.0000"),
        "closed_at_utc": None,
    })
    insert("qa_passes", row)
    return created(qa_pass_out(row))


@bp.route("/qa-passes/<qa_pass_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_qa_pass(qa_pass_id):
    return ok(qa_pass_out(fetch("qa_passes", qa_pass_id)))


@bp.route("/qa-passes", methods=["GET"])
@endpoint(ALL_ROLES)
def list_qa_passes():
    pairs = [
        ("market_plan_id", arg("market_plan_id")),
        ("pass_type", arg("pass_type")),
        ("status", arg("status")),
    ]
    items = [p for p in rows("qa_passes") if match_all(p, pairs)]
    return paginated(items, qa_pass_out, nk_qa_pass)


@bp.route("/qa-passes/<qa_pass_id>/close", methods=["POST"])
@endpoint(TESTERS)
def close_qa_pass(qa_pass_id):
    qa_pass = fetch("qa_passes", qa_pass_id)

    # rung 8 -- the opener may not close their own pass
    require_distinct_actor(qa_pass["opened_by_user_id"])

    if qa_pass["status"] != "OPEN":
        raise ApiError("ERR_QA_PASS_NOT_OPEN")

    plan = fetch("market_plans", qa_pass["market_plan_id"])
    if plan["status"] != "LQA":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET", "The market plan must be in LQA"
        )

    recompute_pass_density(qa_pass)
    if qa_pass["defect_density"] >= DEFECT_DENSITY_CEILING:
        raise ApiError("ERR_DEFECT_DENSITY_EXCEEDED")

    qa_pass["status"] = "CLOSED"
    qa_pass["closed_at_utc"] = db.now()
    touch(qa_pass)
    return ok(qa_pass_out(qa_pass))


@bp.route("/qa-passes/<qa_pass_id>/reopen", methods=["POST"])
@endpoint(TESTERS)
def reopen_qa_pass(qa_pass_id):
    qa_pass = fetch("qa_passes", qa_pass_id)
    if qa_pass["status"] != "CLOSED":
        raise ApiError("ERR_QA_PASS_NOT_CLOSED")

    plan = fetch("market_plans", qa_pass["market_plan_id"])
    if plan["status"] not in ("IN_LOCALIZATION", "LQA"):
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The market plan must be IN_LOCALIZATION or LQA",
        )

    qa_pass["status"] = "OPEN"
    qa_pass["reopen_count"] = qa_pass["reopen_count"] + 1
    qa_pass["closed_at_utc"] = None
    touch(qa_pass)
    return ok(qa_pass_out(qa_pass))
