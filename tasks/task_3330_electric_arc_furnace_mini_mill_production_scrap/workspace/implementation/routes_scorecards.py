"""Division scorecard routes."""
import uuid
from decimal import Decimal
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_int, parse_month, req_str)
from services import (get_mill, get_scorecard, new_common, bump,
                      PROFIT_SHARE_RATE)

bp = Blueprint("scorecards", __name__)


@bp.route("/mills/<millId>/division-scorecards", methods=["POST"])
def create_scorecard(millId):
    require_role("PlantManager")
    get_mill(millId)
    body = get_body()
    period = parse_month(req_str(body, "period"), "period")
    headcount = req_int(body, "headcount", gt=0)
    sc = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "period": period,
        "revenue_cents": 0,
        "material_cost_cents": 0,
        "energy_cost_cents": 0,
        "curtailment_credits_cents": 0,
        "profit_cents": None,
        "profit_pool_cents": None,
        "headcount": headcount,
        "distribution_per_employee_cents": None,
        "remainder_cents": None,
        "status": "OPEN",
        **new_common(),
    }
    db.scorecards[sc["id"]] = sc
    return ok(sc, 201)


@bp.route("/mills/<millId>/division-scorecards", methods=["GET"])
def list_scorecards(millId):
    require_auth()
    get_mill(millId)
    rows = [s for s in db.scorecards.values() if s["mill_id"] == millId]
    return list_response(rows, {"period": "period", "status": "status"})


@bp.route("/mills/<millId>/division-scorecards/<scorecardId>", methods=["GET"])
def get_scorecard_route(millId, scorecardId):
    require_auth()
    get_mill(millId)
    return ok(get_scorecard(scorecardId, millId))


@bp.route("/mills/<millId>/division-scorecards/<scorecardId>/close", methods=["POST"])
def close_scorecard(millId, scorecardId):
    require_role("PlantManager")
    get_mill(millId)
    sc = get_scorecard(scorecardId, millId)
    if sc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "scorecard is not OPEN")
    if not isinstance(sc.get("headcount"), int) or sc["headcount"] <= 0:
        raise err("ERR_INVALID_STATE", "headcount not set")
    profit = sc["revenue_cents"] - sc["material_cost_cents"] - sc["energy_cost_cents"]
    pool = int(Decimal(max(0, profit)) * PROFIT_SHARE_RATE)
    per_emp = pool // sc["headcount"]
    remainder = pool - per_emp * sc["headcount"]
    sc["profit_cents"] = profit
    sc["profit_pool_cents"] = pool
    sc["distribution_per_employee_cents"] = per_emp
    sc["remainder_cents"] = remainder
    sc["status"] = "CLOSED"
    bump(sc)
    return ok(sc)


@bp.route("/mills/<millId>/division-scorecards/<scorecardId>/distribute", methods=["POST"])
def distribute_scorecard(millId, scorecardId):
    require_role("PlantManager")
    get_mill(millId)
    sc = get_scorecard(scorecardId, millId)
    if sc["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "scorecard is not CLOSED")
    sc["status"] = "DISTRIBUTED"
    bump(sc)
    return ok(sc)


# --- flat reads ---------------------------------------------------------------

@bp.route("/mills/division-scorecards", methods=["GET"])
def flat_list_scorecards():
    require_auth()
    return list_response(list(db.scorecards.values()),
                         {"mill_id": "mill_id", "period": "period",
                          "status": "status"})


@bp.route("/mills/division-scorecards/<scorecardId>", methods=["GET"])
def flat_get_scorecard(scorecardId):
    require_auth()
    return ok(get_scorecard(scorecardId))
