"""Coil receipt, roll-forming line time and the mass ledger (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import serializers
import services
import store
from authz import ALL_ROLES, authorize
from common import D
from envelope import created, ok, paginated
from errors import ApiError
from routes_config import find_config
from shape import body, req_dt, req_num, req_str
from store import insert, touch

bp = Blueprint("production", __name__)


def find_lot(row_id):
    row = store.coil_lots.get(row_id)
    if row is None:
        raise ApiError("ERR_COIL_LOT_NOT_FOUND")
    return row


def find_run(row_id):
    row = store.roll_forming_runs.get(row_id)
    if row is None:
        raise ApiError("ERR_ROLL_FORMING_RUN_NOT_FOUND")
    return row


def find_order(row_id):
    row = store.dealer_orders.get(row_id)
    if row is None:
        raise ApiError("ERR_DEALER_ORDER_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# Coil lots
# ---------------------------------------------------------------------------
@bp.post("/coil-lots")
def receive_lot():
    authorize(("ProductionPlanner",))
    payload = body()
    coating_spec_id = req_str(payload, "coating_spec_id")
    heat_number = req_str(payload, "heat_number")
    gauge_mm = req_num(payload, "gauge_mm", minimum="0.8", maximum="6.0")
    received_kg = req_num(payload, "received_kg", minimum="100.0", maximum="200000.0")

    find_config(store.coating_specs, coating_spec_id)

    row = {
        "coating_spec_id": coating_spec_id,
        "heat_number": heat_number,
        "gauge_mm": gauge_mm,
        "received_kg": received_kg,
        "reserved_kg": D("0"),
        "consumed_kg": D("0"),
        "scrap_kg": D("0"),
        "remaining_kg": received_kg,
        "status": "AVAILABLE",
    }
    insert(store.coil_lots, row)
    return created(serializers.coil_lot(row))


@bp.get("/coil-lots")
def list_lots():
    authorize(ALL_ROLES)
    rows = store.ordered(store.coil_lots)
    coating_spec_id = request.args.get("coating_spec_id")
    if coating_spec_id:
        rows = [row for row in rows if row["coating_spec_id"] == coating_spec_id]
    return paginated(rows, serializers.coil_lot)


@bp.get("/coil-lots/<row_id>")
def read_lot(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.coil_lot(find_lot(row_id)))


# ---------------------------------------------------------------------------
# Roll-forming runs
# ---------------------------------------------------------------------------
def _window_conflict(line_id, new_start, new_end, coating_code, buffer_minutes):
    """Half-open line windows; a changeover buffer applies across coatings."""
    buffer = timedelta(minutes=buffer_minutes)
    for existing in store.runs_of_line(line_id):
        if existing["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        start = existing["window_start"]
        end = existing["window_end"]
        if existing["coating_code"] == coating_code:
            if new_start < end and start < new_end:
                return True
        else:
            if new_start < end + buffer and start - buffer < new_end:
                return True
    return False


@bp.post("/roll-forming-runs")
def schedule_run():
    authorize(("ProductionPlanner",))
    payload = body()
    line_id = req_str(payload, "roll_forming_line_id")
    lot_id = req_str(payload, "coil_lot_id")
    order_id = req_str(payload, "dealer_order_id")
    window_start = req_dt(payload, "window_start")
    window_end = req_dt(payload, "window_end")
    planned_kg = req_num(payload, "planned_kg", minimum="1.0", maximum="200000.0")

    line = find_config(store.roll_forming_lines, line_id)
    lot = find_lot(lot_id)
    order = find_order(order_id)

    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_COIL_LOT_NOT_AVAILABLE")

    design = store.bin_designs[order["bin_design_id"]]
    if D(lot["gauge_mm"]) != D(design["sheet_gauge_mm"]):
        raise ApiError("ERR_COIL_GAUGE_MISMATCH")

    if not window_end > window_start:
        raise ApiError("ERR_WINDOW_ORDER_INVALID")

    coating = store.coating_specs[lot["coating_spec_id"]]
    if _window_conflict(
        line_id, window_start, window_end, coating["coating_code"], coating["changeover_minutes"]
    ):
        raise ApiError("ERR_LINE_WINDOW_CONFLICT")

    if D(design["sheet_gauge_mm"]) > D(line["max_gauge_mm"]):
        raise ApiError("ERR_GAUGE_EXCEEDS_LINE_CAPACITY")

    if planned_kg > D(lot["remaining_kg"]):
        raise ApiError("ERR_COIL_INSUFFICIENT_MASS")

    run = {
        "roll_forming_line_id": line_id,
        "coil_lot_id": lot_id,
        "dealer_order_id": order_id,
        "window_start": window_start,
        "window_end": window_end,
        "planned_kg": planned_kg,
        "coating_code": coating["coating_code"],
        "consumed_kg": D("0"),
        "scrap_kg": D("0"),
        "status": "SCHEDULED",
    }
    insert(store.roll_forming_runs, run)
    services.recompute_coil_lot(lot)
    return created(serializers.roll_forming_run(run))


@bp.get("/roll-forming-runs")
def list_runs():
    authorize(ALL_ROLES)
    rows = store.ordered(store.roll_forming_runs)
    for field in ("roll_forming_line_id", "coil_lot_id", "dealer_order_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row[field] == value]
    return paginated(rows, serializers.roll_forming_run)


@bp.get("/roll-forming-runs/<row_id>")
def read_run(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.roll_forming_run(find_run(row_id)))


@bp.post("/roll-forming-runs/<row_id>/complete")
def complete_run(row_id):
    authorize(("ProductionPlanner",))
    payload = body()
    consumed_kg = req_num(payload, "consumed_kg")
    scrap_kg = req_num(payload, "scrap_kg")

    run = find_run(row_id)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE_INVALID")
    if consumed_kg + scrap_kg > D(run["planned_kg"]):
        raise ApiError("ERR_RUN_MASS_EXCEEDS_RESERVED")

    run["consumed_kg"] = consumed_kg
    run["scrap_kg"] = scrap_kg
    run["status"] = "COMPLETED"
    touch(run)

    services.recompute_coil_lot(store.coil_lots[run["coil_lot_id"]])

    order = store.dealer_orders.get(run["dealer_order_id"])
    if order is not None and order["production_status"] == "QUEUED":
        order["production_status"] = "KITTED"
        touch(order)
    return ok(serializers.roll_forming_run(run))


@bp.post("/roll-forming-runs/<row_id>/void")
def void_run(row_id):
    authorize(("ProductionPlanner",))
    run = find_run(row_id)
    if run["status"] not in ("SCHEDULED", "COMPLETED"):
        raise ApiError("ERR_RUN_STATE_INVALID")

    was_completed = run["status"] == "COMPLETED"
    run["consumed_kg"] = D("0")
    run["scrap_kg"] = D("0")
    run["status"] = "VOIDED"
    touch(run)

    services.recompute_coil_lot(store.coil_lots[run["coil_lot_id"]])

    if was_completed:
        order = store.dealer_orders.get(run["dealer_order_id"])
        if order is not None and order["production_status"] == "KITTED":
            order["production_status"] = "QUEUED"
            touch(order)
    return ok(serializers.roll_forming_run(run))
