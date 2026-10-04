"""Clock, mill, and surcharge index routes."""
import uuid
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_enum, req_num, req_int, parse_dt, parse_month)
from services import (get_mill, get_index, new_common, clock_sweep,
                      refresh_posture)

bp = Blueprint("core", __name__)

ALL_ROLES = ("PlantManager", "MillOperator", "Scheduler", "Metallurgist",
             "ProcurementOfficer", "AccountManager", "QualityEngineer",
             "EnergyDispatcher")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("PlantManager")
    body = get_body()
    current = req_str(body, "current_utc")
    dt = parse_dt(current, "current_utc")
    db.set_clock(dt)
    clock_sweep()
    clock = db.get_clock()
    return ok({"current_utc": clock.strftime("%Y-%m-%dT%H:%M:%SZ")})


@bp.route("/mills", methods=["POST"])
def create_mill():
    require_role("PlantManager")
    body = get_body()
    name = req_str(body, "name")
    division = req_enum(body, "division", {"CONSTRUCTION", "AUTOMOTIVE", "ENERGY"})
    cap = req_num(body, "furnace_capacity_tons", gt=0)
    rate = req_num(body, "caster_rate_tph", gt=0)
    mill = {
        "id": str(uuid.uuid4()),
        "name": name,
        "division": division,
        "furnace_capacity_tons": cap,
        "caster_rate_tph": rate,
        "posture": "NORMAL",
        **new_common(),
    }
    db.mills[mill["id"]] = mill
    db.mtr_sequences[mill["id"]] = 0
    return ok(mill, 201)


@bp.route("/mills", methods=["GET"])
def list_mills():
    require_auth()
    for m in db.mills.values():
        refresh_posture(m["id"])
    return list_response(list(db.mills.values()))


@bp.route("/mills/<millId>", methods=["GET"])
def get_mill_route(millId):
    require_auth()
    mill = get_mill(millId)
    refresh_posture(millId)
    return ok(mill)


# --- surcharge indices ------------------------------------------------------

@bp.route("/mills/<millId>/surcharge-indices", methods=["POST"])
def create_index(millId):
    require_role("PlantManager")
    mill = get_mill(millId)
    body = get_body()
    cat = req_enum(body, "grade_category",
                   {"SHREDDED", "BUSHLING", "HMS", "DRI", "PIG_IRON"})
    month = parse_month(req_str(body, "effective_month"), "effective_month")
    price = req_int(body, "price_per_ton_cents", ge=0)
    for row in db.surcharge_indices.values():
        if (row["mill_id"] == millId and row["grade_category"] == cat
                and row["effective_month"] == month and row["status"] == "PUBLISHED"):
            row["status"] = "SUPERSEDED"
    idx = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "grade_category": cat,
        "effective_month": month,
        "price_per_ton_cents": price,
        "status": "PUBLISHED",
        "created_at": db.ts_now(),
    }
    db.surcharge_indices[idx["id"]] = idx
    return ok(idx, 201)


@bp.route("/mills/<millId>/surcharge-indices", methods=["GET"])
def list_indices(millId):
    require_auth()
    get_mill(millId)
    rows = [i for i in db.surcharge_indices.values() if i["mill_id"] == millId]
    return list_response(rows, {"grade_category": "grade_category",
                                "effective_month": "effective_month",
                                "status": "status"})


@bp.route("/mills/<millId>/surcharge-indices/by-id/<indexId>", methods=["GET"])
def get_index_route(millId, indexId):
    require_auth()
    get_mill(millId)
    return ok(get_index(indexId, millId))


@bp.route("/mills/surcharge-indices", methods=["GET"])
def flat_list_indices():
    require_auth()
    return list_response(list(db.surcharge_indices.values()),
                         {"mill_id": "mill_id", "grade_category": "grade_category",
                          "effective_month": "effective_month", "status": "status"})


@bp.route("/mills/surcharge-indices/<indexId>", methods=["GET"])
def flat_get_index(indexId):
    require_auth()
    return ok(get_index(indexId))
