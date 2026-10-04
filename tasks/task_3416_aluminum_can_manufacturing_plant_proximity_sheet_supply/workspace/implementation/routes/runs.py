"""Production run creation and reads. The create path walks the full
nine-gate validation gauntlet of PRD section 2.7."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, new_id, now_iso, next_seq, touch
from errors import (ApiError, ERR_NOT_FOUND, ERR_VALIDATION,
                    ERR_LINE_NOT_FOUND,
                    ERR_FORMAT_NOT_FOUND, ERR_STALE_VERSION,
                    ERR_AGREEMENT_NOT_ACTIVE, ERR_FORMAT_NOT_QUALIFIED,
                    ERR_LINE_QUALITY_HOLD, ERR_PLANT_LOCKDOWN,
                    ERR_LINE_WINDOW_OVERLAP, ERR_CHANGEOVER_BUFFER_VIOLATION,
                    ERR_WAREHOUSE_CAPACITY_EXCEEDED)
from middleware import actor, require_role
from response import ok_object, ok_list
from services import calc
from services.serialize import run_public
from validation import body_json, req_str, req_int, parse_iso_dt, pagination_args

bp = Blueprint("runs", __name__)


def get_run_or_404(rid):
    run = store["runs"].get(rid)
    if run is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Production run not found.")
    return run


@bp.post("/supply-agreements/<aid>/production-runs")
def create_run(aid):
    _, role = actor()
    require_role(role, ["LineScheduler"])
    # Gate 3: body shape
    data = body_json()
    line_id = req_str(data, "line_id")
    format_id = req_str(data, "format_id")
    scheduled_qty = req_int(data, "scheduled_qty", minimum=calc.MIN_RUN_QTY)
    graphics_code = req_str(data, "graphics_code")
    window_start = req_str(data, "window_start")
    window_end = req_str(data, "window_end")
    ws_dt = parse_iso_dt(window_start, "window_start")
    we_dt = parse_iso_dt(window_end, "window_end")
    if we_dt <= ws_dt:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "window_end must be strictly after window_start.")
    expected_version = req_int(data, "expected_agreement_version")
    # Gate 4: existence — path first, then body FKs in declared input order
    agr = store["agreements"].get(aid)
    if agr is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Supply agreement not found.")
    line = store["lines"].get(line_id)
    if line is None:
        raise ApiError(ERR_LINE_NOT_FOUND[0], ERR_LINE_NOT_FOUND[1],
                       "line_id does not match an existing production line.")
    fmt = store["formats"].get(format_id)
    if fmt is None:
        raise ApiError(ERR_FORMAT_NOT_FOUND[0], ERR_FORMAT_NOT_FOUND[1],
                       "format_id does not match an existing can format.")
    # Gate 5: OCC on the agreement version
    if expected_version != agr["version"]:
        raise ApiError(ERR_STALE_VERSION[0], ERR_STALE_VERSION[1],
                       "expected_agreement_version does not match the current agreement version.")
    # Gate 6: state — path-parent agreement first, then body-FK format
    if agr["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE[0], ERR_AGREEMENT_NOT_ACTIVE[1],
                       "Run creation requires the agreement to be ACTIVE.")
    if fmt["status"] != "QUALIFIED":
        raise ApiError(ERR_FORMAT_NOT_QUALIFIED[0], ERR_FORMAT_NOT_QUALIFIED[1],
                       "Run creation requires the format to be QUALIFIED.")
    # Gate 7: safety — line quality hold before plant lockdown
    plant = store["plants"][line["plant_id"]]
    if line["operational_status"] == "QUALITY_HOLD":
        raise ApiError(ERR_LINE_QUALITY_HOLD[0], ERR_LINE_QUALITY_HOLD[1],
                       "Line is in QUALITY_HOLD; run creation is blocked.")
    if calc.plant_posture(plant) == "LOCKDOWN":
        raise ApiError(ERR_PLANT_LOCKDOWN[0], ERR_PLANT_LOCKDOWN[1],
                       "Plant posture is LOCKDOWN; run creation is blocked.")
    # Gate 8: temporal — half-open window overlap before changeover buffer
    for r in store["runs"].values():
        if r["line_id"] != line_id or r["status"] not in calc.OPEN_RUN_STATUSES:
            continue
        if r["_window_start_dt"] < we_dt and ws_dt < r["_window_end_dt"]:
            raise ApiError(ERR_LINE_WINDOW_OVERLAP[0], ERR_LINE_WINDOW_OVERLAP[1],
                           "Run window overlaps another open run on the same line.")
    prev = calc.previous_run(line_id, ws_dt)
    if prev is not None and prev["graphics_code"] != graphics_code:
        earliest = prev["_window_end_dt"] + timedelta(minutes=calc.CHANGEOVER_BUFFER_MINUTES)
        if ws_dt < earliest:
            raise ApiError(ERR_CHANGEOVER_BUFFER_VIOLATION[0], ERR_CHANGEOVER_BUFFER_VIOLATION[1],
                           "Graphics changeover requires >= %d minutes after the previous run."
                           % calc.CHANGEOVER_BUFFER_MINUTES)
    # Gate 9: business — warehouse capacity (equality allowed, strict > rejects)
    if calc.projected_warehouse_units(plant) + scheduled_qty > plant["warehouse_capacity_units"]:
        raise ApiError(ERR_WAREHOUSE_CAPACITY_EXCEEDED[0], ERR_WAREHOUSE_CAPACITY_EXCEEDED[1],
                       "projected_warehouse_units + scheduled_qty would exceed capacity.")
    ts = now_iso()
    run = {
        "id": new_id(),
        "agreement_id": agr["id"],
        "line_id": line_id,
        "format_id": format_id,
        "scheduled_qty": scheduled_qty,
        "graphics_code": graphics_code,
        "window_start": window_start,
        "window_end": window_end,
        "produced_qty": None,
        "spoiled_qty": None,
        "sheet_lbs_consumed": None,
        "effective_spoilage_pct": None,
        "spoilage_flag": False,
        "provisional_unit_price_cents_per_1000": None,
        "final_unit_price_cents_per_1000": None,
        "settled_amount_cents": None,
        "tier_delta_cents": 0,
        "status": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
        "_window_start_dt": ws_dt,
        "_window_end_dt": we_dt,
        "_completion_year": None,
    }
    store["runs"][run["id"]] = run
    touch(agr)  # run creation increments the parent agreement's version
    return ok_object(run_public(run), code=201)


@bp.get("/production-runs")
def list_runs():
    actor()
    limit, offset = pagination_args()
    line_id = request.args.get("line_id")
    agreement_id = request.args.get("agreement_id")
    format_id = request.args.get("format_id")
    status = request.args.get("status")
    items = sorted(store["runs"].values(), key=lambda r: r["_created_sort"])
    if line_id is not None:
        items = [r for r in items if r["line_id"] == line_id]
    if agreement_id is not None:
        items = [r for r in items if r["agreement_id"] == agreement_id]
    if format_id is not None:
        items = [r for r in items if r["format_id"] == format_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([run_public(r) for r in page], limit, offset, total)


@bp.get("/production-runs/<rid>")
def get_run(rid):
    actor()
    return ok_object(run_public(get_run_or_404(rid)))
