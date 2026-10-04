"""Energy interval and mill test report routes."""
import uuid
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_num, parse_dt)
from services import get_mill, get_heat, get_order, refresh_posture, heat_sheet

bp = Blueprint("intervals_mtrs", __name__)


@bp.route("/mills/<millId>/heats/<heatId>/energy-intervals", methods=["POST"])
def add_interval(millId, heatId):
    require_role("MillOperator", "EnergyDispatcher")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    body = get_body()
    start = parse_dt(req_str(body, "interval_start"), "interval_start")
    end = parse_dt(req_str(body, "interval_end"), "interval_end")
    kwh = req_num(body, "kwh", gt=0)
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "interval_end must be after interval_start")
    refresh_posture(millId)
    interval = {
        "id": str(uuid.uuid4()),
        "heat_id": heatId,
        "interval_start": start,
        "interval_end": end,
        "kwh": kwh,
        "posture_at_interval": db.mills[millId]["posture"],
        "created_at": db.ts_now(),
    }
    db.intervals[interval["id"]] = interval
    heat["energy_kwh"] = heat.get("energy_kwh", 0.0) + kwh
    return ok(interval, 201)


@bp.route("/mills/<millId>/heats/<heatId>/energy-intervals", methods=["GET"])
def list_intervals(millId, heatId):
    require_auth()
    get_mill(millId)
    get_heat(heatId, millId)
    rows = [i for i in db.intervals.values() if i["heat_id"] == heatId]
    return list_response(rows)


@bp.route("/mills/<millId>/heats/<heatId>/mill-test-reports", methods=["POST"])
def issue_mtr(millId, heatId):
    require_role("QualityEngineer")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    body = get_body()
    order_id = req_str(body, "order_id")
    order = get_order(order_id)
    if heat["status"] != "CAST":
        raise err("ERR_MTR_NOT_ISSUABLE", "heat is not CAST")
    sheet = heat_sheet(heatId)
    if sheet is None or sheet["status"] != "CONFIRMED":
        raise err("ERR_MTR_NOT_ISSUABLE", "meltdown sheet is not CONFIRMED")
    grade = db.grades[heat["grade_id"]]
    intervals = [i for i in db.intervals.values() if i["heat_id"] == heatId]
    if grade["requires_energy_certified"]:
        if len(intervals) == 0:
            raise err("ERR_MTR_NOT_ISSUABLE",
                      "CERTIFIED grade requires at least one energy interval")
        energy_certified = all(i["posture_at_interval"] != "INTERRUPTED"
                               for i in intervals)
    else:
        energy_certified = True
    db.mtr_sequences[millId] = db.mtr_sequences.get(millId, 0) + 1
    seq = db.mtr_sequences[millId]
    mtr = {
        "id": str(uuid.uuid4()),
        "heat_id": heatId,
        "order_id": order_id,
        "report_no": f"MTR-{seq}",
        "chemistry_snapshot": {
            "cu_pct": sheet["cu_pct"],
            "mn_pct": sheet["mn_pct"],
            "revision_no": sheet["revision_no"],
        },
        "energy_certified": energy_certified,
        "created_at": db.ts_now(),
    }
    db.mtrs[mtr["id"]] = mtr
    return ok(mtr, 201)


@bp.route("/mills/<millId>/heats/<heatId>/mill-test-reports", methods=["GET"])
def list_mtrs(millId, heatId):
    require_auth()
    get_mill(millId)
    get_heat(heatId, millId)
    rows = [m for m in db.mtrs.values() if m["heat_id"] == heatId]
    return list_response(rows, {"order_id": "order_id"})


# --- flat reads ---------------------------------------------------------------

@bp.route("/mills/energy-intervals", methods=["GET"])
def flat_list_intervals():
    require_auth()
    return list_response(list(db.intervals.values()), {"heat_id": "heat_id"})


@bp.route("/mills/energy-intervals/<intervalId>", methods=["GET"])
def flat_get_interval(intervalId):
    require_auth()
    i = db.intervals.get(intervalId)
    if i is None:
        raise err("ERR_INVALID_REQUEST", "interval not found")
    return ok(i)


@bp.route("/mills/mill-test-reports", methods=["GET"])
def flat_list_mtrs():
    require_auth()
    return list_response(list(db.mtrs.values()),
                         {"heat_id": "heat_id", "order_id": "order_id"})


@bp.route("/mills/mill-test-reports/<mtrId>", methods=["GET"])
def flat_get_mtr(mtrId):
    require_auth()
    m = db.mtrs.get(mtrId)
    if m is None:
        raise err("ERR_INVALID_REQUEST", "MTR not found")
    return ok(m)
