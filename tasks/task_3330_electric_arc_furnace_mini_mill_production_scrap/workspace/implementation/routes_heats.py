"""Heat, charge line, meltdown sheet, tap/cast/abort routes."""
import uuid
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_num, parse_dt)
from services import (get_mill, get_heat, get_grade, get_lot, get_sheet,
                      new_common, bump, heat_lines, heat_sheet,
                      check_heat_grid, blend_check, apply_charge, abort_heat,
                      posture_gate, compute_scrap_surcharge_credit,
                      open_scorecard, recompute_scorecard_profit)

bp = Blueprint("heats", __name__)


@bp.route("/mills/<millId>/heats", methods=["POST"])
def create_heat(millId):
    require_role("MillOperator")
    mill = get_mill(millId)
    body = get_body()
    number = req_str(body, "heat_number")
    grade_id = req_str(body, "grade_id")
    target = req_num(body, "target_tap_weight_tons", gt=0)
    tap_at = parse_dt(req_str(body, "planned_tap_at"), "planned_tap_at")
    grade = get_grade(grade_id, millId)
    if target > mill["furnace_capacity_tons"]:
        raise err("ERR_INVALID_REQUEST", "target exceeds furnace capacity")
    check_heat_grid(millId, tap_at)
    heat = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "heat_number": number,
        "grade_id": grade_id,
        "target_tap_weight_tons": target,
        "planned_tap_at": tap_at,
        "energy_kwh": 0.0,
        "charge_cost_cents": None,
        "scrap_surcharge_credit_cents": None,
        "status": "PLANNED",
        **new_common(),
    }
    db.heats[heat["id"]] = heat
    return ok(heat, 201)


@bp.route("/mills/<millId>/heats", methods=["GET"])
def list_heats(millId):
    require_auth()
    get_mill(millId)
    rows = [h for h in db.heats.values() if h["mill_id"] == millId]
    return list_response(rows, {"status": "status", "grade_id": "grade_id"})


@bp.route("/mills/<millId>/heats/<heatId>", methods=["GET"])
def get_heat_route(millId, heatId):
    require_auth()
    get_mill(millId)
    return ok(get_heat(heatId, millId))


@bp.route("/mills/<millId>/heats/<heatId>/charges", methods=["POST"])
def add_charge(millId, heatId):
    require_role("MillOperator")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    body = get_body()
    lot_id = req_str(body, "scrap_lot_id")
    tons = req_num(body, "tons", gt=0)
    lot = get_lot(lot_id)
    if heat["status"] not in ("PLANNED", "CHARGED"):
        raise err("ERR_INVALID_STATE", "heat must be PLANNED or CHARGED")
    posture_gate(heat)
    contract = db.contracts[lot["contract_id"]]
    if contract["status"] != "OPEN":
        raise err("ERR_CONTRACT_NOT_OPEN", "contract is not OPEN")
    if lot["status"] not in ("RECEIVED", "PARTIALLY_CONSUMED"):
        raise err("ERR_LOT_DEPLETED", "lot has no remaining tonnage")
    if tons > lot["remaining_tons"]:
        raise err("ERR_LOT_DEPLETED", "requested tons exceed remaining_tons")
    grade = db.grades[heat["grade_id"]]
    blend_check(heat, grade, lot, tons)
    check_heat_grid(millId, heat["planned_tap_at"], exclude_heat_id=heatId)
    line = apply_charge(heat, lot, tons)
    if heat["status"] == "PLANNED":
        heat["status"] = "CHARGED"
        bump(heat)
    return ok(line, 201)


@bp.route("/mills/<millId>/heats/<heatId>/charges", methods=["GET"])
def list_charges(millId, heatId):
    require_auth()
    get_mill(millId)
    get_heat(heatId, millId)
    rows = heat_lines(heatId)
    return list_response(rows, {"scrap_lot_id": "scrap_lot_id"})


# --- meltdown sheets ---------------------------------------------------------

@bp.route("/mills/<millId>/heats/<heatId>/meltdown-sheets", methods=["POST"])
def create_sheet(millId, heatId):
    require_role("Metallurgist")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    body = get_body()
    cu = req_num(body, "cu_pct", ge=0.0, le=0.02)
    mn = req_num(body, "mn_pct", ge=0.0, le=0.05)
    if heat["status"] != "CHARGED":
        raise err("ERR_INVALID_STATE", "heat must be CHARGED")
    if heat_sheet(heatId) is not None:
        raise err("ERR_INVALID_STATE", "heat already has a meltdown sheet")
    grade = db.grades[heat["grade_id"]]
    chem_ok = (cu <= grade["cu_max_pct"]
               and grade["mn_min_pct"] <= mn <= grade["mn_max_pct"])
    sheet = {
        "id": str(uuid.uuid4()),
        "heat_id": heatId,
        "revision_no": 1,
        "cu_pct": cu,
        "mn_pct": mn,
        "chem_ok": chem_ok,
        "status": "RECORDED",
        **new_common(),
    }
    db.meltdown_sheets[sheet["id"]] = sheet
    return ok(sheet, 201)


@bp.route("/mills/<millId>/heats/<heatId>/meltdown-sheets", methods=["GET"])
def list_sheets(millId, heatId):
    require_auth()
    get_mill(millId)
    get_heat(heatId, millId)
    rows = [s for s in db.meltdown_sheets.values() if s["heat_id"] == heatId]
    return list_response(rows)


@bp.route("/mills/<millId>/heats/<heatId>/meltdown-sheets/<sheetId>/revise", methods=["POST"])
def revise_sheet(millId, heatId, sheetId):
    require_role("Metallurgist")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    sheet = get_sheet(sheetId, heatId)
    body = get_body()
    cu = req_num(body, "cu_pct", ge=0.0, le=0.02)
    mn = req_num(body, "mn_pct", ge=0.0, le=0.05)
    if heat["status"] != "CHARGED":
        raise err("ERR_INVALID_STATE", "heat must be CHARGED")
    if sheet["status"] not in ("RECORDED", "REVISED"):
        raise err("ERR_INVALID_STATE", "sheet is not revisable")
    grade = db.grades[heat["grade_id"]]
    sheet["cu_pct"] = cu
    sheet["mn_pct"] = mn
    sheet["chem_ok"] = (cu <= grade["cu_max_pct"]
                        and grade["mn_min_pct"] <= mn <= grade["mn_max_pct"])
    sheet["revision_no"] += 1
    sheet["status"] = "REVISED" if sheet["status"] == "RECORDED" else "RECORDED"
    bump(sheet)
    return ok(sheet)


@bp.route("/mills/<millId>/heats/<heatId>/meltdown-sheets/<sheetId>/confirm", methods=["POST"])
def confirm_sheet(millId, heatId, sheetId):
    require_role("Metallurgist")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    sheet = get_sheet(sheetId, heatId)
    if heat["status"] != "CHARGED":
        raise err("ERR_INVALID_STATE", "heat must be CHARGED")
    if sheet["status"] not in ("RECORDED", "REVISED"):
        raise err("ERR_INVALID_STATE", "sheet is not confirmable")
    if not sheet["chem_ok"]:
        raise err("ERR_CHEMISTRY_OUT_OF_SPEC", "chemistry outside grade band")
    sheet["status"] = "CONFIRMED"
    bump(sheet)
    heat["status"] = "MELTDOWN_LOCKED"
    heat["scrap_surcharge_credit_cents"] = compute_scrap_surcharge_credit(heat)
    bump(heat)
    return ok(sheet)


@bp.route("/mills/<millId>/heats/<heatId>/meltdown-sheets/<sheetId>/reject", methods=["POST"])
def reject_sheet(millId, heatId, sheetId):
    require_role("Metallurgist")
    get_mill(millId)
    get_heat(heatId, millId)
    sheet = get_sheet(sheetId, heatId)
    if sheet["status"] not in ("RECORDED", "REVISED"):
        raise err("ERR_INVALID_STATE", "sheet is not rejectable")
    sheet["status"] = "REJECTED"
    bump(sheet)
    return ok(sheet)


# --- tap / cast / abort ------------------------------------------------------

@bp.route("/mills/<millId>/heats/<heatId>/tap", methods=["POST"])
def tap_heat(millId, heatId):
    require_role("MillOperator")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    if heat["status"] != "MELTDOWN_LOCKED":
        raise err("ERR_INVALID_STATE", "heat must be MELTDOWN_LOCKED")
    posture_gate(heat)
    heat["charge_cost_cents"] = sum(l["line_cost_cents"] for l in heat_lines(heatId))
    heat["status"] = "TAPPED"
    bump(heat)
    return ok(heat)


@bp.route("/mills/<millId>/heats/<heatId>/cast", methods=["POST"])
def cast_heat(millId, heatId):
    require_role("MillOperator")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    if heat["status"] != "TAPPED":
        raise err("ERR_INVALID_STATE", "heat must be TAPPED")
    period = heat["planned_tap_at"].strftime("%Y-%m")
    sc = open_scorecard(millId, period)
    if sc is not None:
        sc["material_cost_cents"] += heat["charge_cost_cents"] or 0
        recompute_scorecard_profit(sc)
    heat["status"] = "CAST"
    bump(heat)
    return ok(heat)


@bp.route("/mills/<millId>/heats/<heatId>/abort", methods=["POST"])
def abort_heat_route(millId, heatId):
    require_role("MillOperator")
    get_mill(millId)
    heat = get_heat(heatId, millId)
    if heat["status"] not in ("PLANNED", "CHARGED", "MELTDOWN_LOCKED"):
        raise err("ERR_INVALID_STATE", "heat cannot be aborted from this state")
    abort_heat(heat)
    return ok(heat)


# --- flat reads ---------------------------------------------------------------

@bp.route("/mills/heats", methods=["GET"])
def flat_list_heats():
    require_auth()
    return list_response(list(db.heats.values()),
                         {"mill_id": "mill_id", "grade_id": "grade_id",
                          "status": "status"})


@bp.route("/mills/heats/<heatId>", methods=["GET"])
def flat_get_heat(heatId):
    require_auth()
    return ok(get_heat(heatId))


@bp.route("/mills/charges", methods=["GET"])
def flat_list_charges():
    require_auth()
    return list_response(list(db.charge_lines.values()),
                         {"heat_id": "heat_id", "scrap_lot_id": "scrap_lot_id"})


@bp.route("/mills/charges/<lineId>", methods=["GET"])
def flat_get_charge(lineId):
    require_auth()
    line = db.charge_lines.get(lineId)
    if line is None:
        raise err("ERR_INVALID_REQUEST", "charge line not found")
    return ok(line)


@bp.route("/mills/meltdown-sheets", methods=["GET"])
def flat_list_sheets():
    require_auth()
    return list_response(list(db.meltdown_sheets.values()),
                         {"heat_id": "heat_id", "status": "status"})


@bp.route("/mills/meltdown-sheets/<sheetId>", methods=["GET"])
def flat_get_sheet(sheetId):
    require_auth()
    return ok(get_sheet(sheetId))
