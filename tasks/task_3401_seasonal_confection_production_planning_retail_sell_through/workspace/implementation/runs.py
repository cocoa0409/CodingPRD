"""ProductionRun routes: create (line overlap + changeover), read, list,
start, complete (creates the inventory lot, capacity gates), cancel."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, next_lot_code, touch
from domain import (
    get_run, ser_run, get_product, warehouse_load,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    ERR_WAREHOUSE_NOT_FOUND, ERR_INVALID_STATE, ERR_PRODUCT_PROGRAM_MISMATCH,
    ERR_PRODUCTION_DEADLINE_VIOLATION, ERR_LINE_SCHEDULE_OVERLAP,
    ERR_CHANGEOVER_VIOLATION, ERR_WAREHOUSE_FULL, ERR_WAREHOUSE_CONGESTED_SEASONAL,
)
from middleware import authorize, ROLE_PRODUCTION_PLANNER, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_dt

bp = Blueprint("runs", __name__)

RUN_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETE", "CANCELLED")


@bp.post("/confection/production-runs")
def create_run():
    data = json_body()
    product_id = v_str(data, "product_id")
    line_code = v_str(data, "line_code")
    planned_units = v_int(data, "planned_units", min_v=1)
    start_dt, start_raw = v_dt(data, "scheduled_start_on")
    end_dt, end_raw = v_dt(data, "scheduled_end_on")
    if end_dt <= start_dt:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "scheduled_end_on must be later than scheduled_start_on")
    program_id = data.get("program_id", None)
    if program_id is not None and not isinstance(program_id, str):
        raise ApiError(400, ERR_INVALID_REQUEST, "field 'program_id' must be a string or null")

    authorize(ROLE_PRODUCTION_PLANNER)

    # Body FK existence in declared input order: program_id, then product_id.
    program = None
    if program_id is not None:
        program = db.programs.get(program_id)
        if program is None:
            raise ApiError(404, ERR_PROGRAM_NOT_FOUND,
                           "SeasonalProgram %s does not exist" % program_id)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(404, ERR_PRODUCT_NOT_FOUND,
                       "Product %s does not exist" % product_id)

    # Temporal (priority 9): production deadline, then overlap, then changeover.
    if product["kind"] == "SEASONAL" and program is not None:
        if end_dt > program["_production_deadline_dt"]:
            raise ApiError(422, ERR_PRODUCTION_DEADLINE_VIOLATION,
                           "scheduled_end_on falls after the program's production_deadline_on")

    others = [r for r in db.runs.values()
              if r["line_code"] == line_code and r["status"] != "CANCELLED"]
    # OVERLAP: half-open [start, end) intersection; back-to-back touching is allowed.
    for other in others:
        if other["_start_dt"] < end_dt and start_dt < other["_end_dt"]:
            raise ApiError(409, ERR_LINE_SCHEDULE_OVERLAP,
                           "the schedule overlaps an existing run on line %s" % line_code)
    # CHANGEOVER: the prior run is the one with the greatest end <= new start.
    prior = None
    for other in others:
        if other["_end_dt"] <= start_dt:
            if prior is None or other["_end_dt"] > prior["_end_dt"]:
                prior = other
    if prior is not None:
        prior_kind = db.products[prior["product_id"]]["kind"]
        if prior_kind != product["kind"]:
            if start_dt < prior["_end_dt"] + timedelta(hours=8):
                raise ApiError(422, ERR_CHANGEOVER_VIOLATION,
                               "a kind switch on this line requires an 8-hour changeover gap")

    # Structural (priority 10): product/program coherence.
    if product["kind"] == "SEASONAL":
        if program_id is None or product["program_id"] != program_id:
            raise ApiError(422, ERR_PRODUCT_PROGRAM_MISMATCH,
                           "a SEASONAL run must name the program of its product")
    else:
        if program_id is not None:
            raise ApiError(422, ERR_PRODUCT_PROGRAM_MISMATCH,
                           "an EVERYDAY run must carry a null program_id")

    run = _create_entity(db.runs, {
        "program_id": program_id,
        "product_id": product_id,
        "line_code": line_code,
        "planned_units": planned_units,
        "produced_units": 0,
        "scheduled_start_on": start_raw,
        "scheduled_end_on": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "completed_warehouse_id": None,
        "status": "SCHEDULED",
    })
    return created(ser_run(run))


@bp.get("/confection/production-runs/<run_id>")
def read_run(run_id):
    authorize(*ALL_ROLES)
    return ok(ser_run(get_run(run_id)))


@bp.get("/confection/production-runs")
def list_runs():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.runs.values())
    for param in ("line_code", "product_id", "program_id", "status", "completed_warehouse_id"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_run(r) for r in page], total, limit, offset)


@bp.post("/confection/production-runs/<run_id>/start")
def start_run(run_id):
    authorize(ROLE_PRODUCTION_PLANNER)
    run = get_run(run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a SCHEDULED run can be started")
    product = get_product(run["product_id"])
    if product["kind"] == "SEASONAL":
        program = db.programs.get(run["program_id"])
        if program is None or program["status"] not in ("LOCKED", "IN_PRODUCTION"):
            raise ApiError(409, ERR_INVALID_STATE,
                           "seasonal production requires the program to be LOCKED or IN_PRODUCTION")
    run["status"] = "IN_PROGRESS"
    touch(run)
    return ok(ser_run(run))


@bp.post("/confection/production-runs/<run_id>/complete")
def complete_run(run_id):
    data = json_body()
    produced_units = v_int(data, "produced_units", min_v=0)
    warehouse_id = v_str(data, "warehouse_id")

    authorize(ROLE_PRODUCTION_PLANNER)
    run = get_run(run_id)

    # Body FK existence (priority 5) precedes the state check (priority 7).
    warehouse = db.warehouses.get(warehouse_id)
    if warehouse is None:
        raise ApiError(404, ERR_WAREHOUSE_NOT_FOUND,
                       "Warehouse %s does not exist" % warehouse_id)

    if run["status"] != "IN_PROGRESS":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only an IN_PROGRESS run can be completed")

    # Capacity gates (priority 11): FULL/overflow first, then the CONGESTED
    # seasonal inbound block.
    in_use, _quarantined, posture = warehouse_load(warehouse_id)
    if posture == "FULL" or in_use + produced_units > warehouse["capacity_units"]:
        raise ApiError(409, ERR_WAREHOUSE_FULL,
                       "the warehouse cannot accept these units without exceeding capacity")
    product = get_product(run["product_id"])
    if posture == "CONGESTED" and product["kind"] == "SEASONAL":
        raise ApiError(409, ERR_WAREHOUSE_CONGESTED_SEASONAL,
                       "a CONGESTED warehouse refuses additional SEASONAL lots")

    run["produced_units"] = produced_units
    run["completed_warehouse_id"] = warehouse_id
    run["status"] = "COMPLETE"
    touch(run)

    # Cascade LINK 1: exactly one InventoryLot per completing run.
    _create_entity(db.lots, {
        "product_id": run["product_id"],
        "warehouse_id": warehouse_id,
        "production_run_id": run["id"],
        "lot_code": next_lot_code(),
        "units_on_hand": produced_units,
        "status": "AVAILABLE",
    })
    return ok(ser_run(run))


@bp.post("/confection/production-runs/<run_id>/cancel")
def cancel_run(run_id):
    authorize(ROLE_PRODUCTION_PLANNER)
    run = get_run(run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a SCHEDULED run can be cancelled")
    run["status"] = "CANCELLED"
    touch(run)
    return ok(ser_run(run))
