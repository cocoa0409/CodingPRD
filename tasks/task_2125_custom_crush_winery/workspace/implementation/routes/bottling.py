"""Bottling: lines, runs, the dry-goods waterfall and run completion."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import ALL_ROLES, CELLAR_SUPERVISOR, FACILITY_ADMIN, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_CROSS_CONTRACT_REFERENCE,
    ERR_DRY_GOODS_SHORTAGE,
    ERR_DUPLICATE_LINE_CODE,
    ERR_INSUFFICIENT_LOT_VOLUME,
    ERR_LINE_DAILY_CAPACITY_EXCEEDED,
    ERR_LINE_SLOT_CONFLICT,
    ERR_LINE_UNAVAILABLE,
)
from helpers import declared, run_list
from store import db, iso, new_entity, rhu, sort_key, touch
from validation import bad, v_datetime, v_enum, v_int, v_number, v_string

D = Decimal
bp = Blueprint("bottling", __name__)

LINE_ACTIONS = {
    "SET_MAINTENANCE": [FACILITY_ADMIN],
    "SET_AVAILABLE": [FACILITY_ADMIN],
}
RUN_ACTIONS = {
    "RESERVE_SUPPLIES": [CELLAR_SUPERVISOR],
    "COMPLETE": [CELLAR_SUPERVISOR],
    "CANCEL": [CELLAR_SUPERVISOR],
}
BOTTLE_SIZES = (375, 750, 1500)
LIVE_RUN_STATUSES = ("SCHEDULED", "SUPPLIES_RESERVED")


# ---------------------------------------------------------------------------
# BottlingLine
# ---------------------------------------------------------------------------
@bp.route("/bottling-lines", methods=["POST"])
def create_line():
    ctx = guard([FACILITY_ADMIN])
    body = ctx.body
    code = v_string(body, "line_code")
    cases_per_hour = v_int(body, "cases_per_hour", gt=0)
    changeover = v_int(body, "changeover_minutes", ge=0)
    daily_capacity = v_number(body, "daily_capacity_hours", required=False,
                              default=D(16), gt=0)

    for existing in db.lines.values():
        if existing["line_code"] == code:
            raise ApiError(ERR_DUPLICATE_LINE_CODE,
                           "Line code '%s' is already held." % code)

    line = new_entity({
        "line_code": code,
        "cases_per_hour": cases_per_hour,
        "changeover_minutes": changeover,
        "daily_capacity_hours": daily_capacity,
        "status": "AVAILABLE",
    })
    db.lines[line["id"]] = line
    return respond(domain.serialize(line), 201)


@bp.route("/bottling-lines/<line_id>", methods=["GET"])
def read_line(line_id):
    guard(ALL_ROLES, read_body=False)
    return respond(domain.serialize(domain.get_line(line_id)))


@bp.route("/bottling-lines", methods=["GET"])
def list_lines():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.lines.values(), ctx, domain.serialize,
                    filters=(("status", "status"),))


@bp.route("/bottling-lines/<line_id>/status", methods=["POST"])
def line_status(line_id):
    ctx = guard([FACILITY_ADMIN], LINE_ACTIONS)
    action = v_enum(ctx.body, "action", set(LINE_ACTIONS))
    line = domain.get_line(line_id)

    if action == "SET_MAINTENANCE":
        declared(line["status"] == "AVAILABLE")
        line["status"] = "MAINTENANCE"
    else:
        declared(line["status"] == "MAINTENANCE")
        line["status"] = "AVAILABLE"

    touch(line)
    return respond(domain.serialize(line))


# ---------------------------------------------------------------------------
# BottlingRun
# ---------------------------------------------------------------------------
@bp.route("/bottling-runs", methods=["POST"])
def create_run():
    ctx = guard([CELLAR_SUPERVISOR])
    body = ctx.body
    lot_id = v_string(body, "lot_id")
    line_id = v_string(body, "line_id")
    start_raw, start_dt = v_datetime(body, "scheduled_start")
    bottle_size_ml = v_int(body, "bottle_size_ml")
    if bottle_size_ml not in BOTTLE_SIZES:
        bad("Field 'bottle_size_ml' must be one of 375, 750, 1500.")
    cases_planned = v_int(body, "cases_planned", ge=1)

    lot = domain.get_lot(lot_id)
    line = domain.get_line(line_id)
    scope(ctx, domain.lot_client_id(lot))

    # Rung 40 -- the line must be AVAILABLE.
    if line["status"] != "AVAILABLE":
        raise ApiError(ERR_LINE_UNAVAILABLE, "The bottling line is in MAINTENANCE.")

    hours = calc.run_hours(cases_planned, line["cases_per_hour"])
    end_dt = (start_dt + timedelta(seconds=int(D(hours) * D(3600)))
              + timedelta(minutes=int(line["changeover_minutes"])))
    consumed = calc.gallons_consumed(cases_planned, bottle_size_ml)

    # Rung 70 -- line occupancy is a CLOSED interval; touching endpoints collide.
    for other in db.runs.values():
        if other["line_id"] != line["id"]:
            continue
        if other["status"] not in LIVE_RUN_STATUSES:
            continue
        if start_dt <= other["_end_dt"] and other["_start_dt"] <= end_dt:
            raise ApiError(ERR_LINE_SLOT_CONFLICT,
                           "The computed window collides with another run.")

    # Rung 72 -- aggregate daily capacity for one UTC calendar day.
    same_day = D(0)
    for other in db.runs.values():
        if other["line_id"] != line["id"]:
            continue
        if other["status"] not in LIVE_RUN_STATUSES:
            continue
        if other["_start_dt"].date() == start_dt.date():
            same_day += D(other["run_hours"])
    if same_day + D(hours) > D(line["daily_capacity_hours"]):
        raise ApiError(ERR_LINE_DAILY_CAPACITY_EXCEEDED,
                       "The line's daily capacity would be exceeded.")

    run = new_entity({
        "lot_id": lot_id,
        "line_id": line_id,
        "scheduled_start": start_raw,
        "scheduled_end": iso(end_dt),
        "run_hours": hours,
        "bottle_size_ml": bottle_size_ml,
        "cases_planned": cases_planned,
        "cases_actual": None,
        "gallons_consumed": consumed,
        "supply_reservations": [],
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_completed_dt": None,
    })
    db.runs[run["id"]] = run
    return respond(domain.serialize(run), 201)


@bp.route("/bottling-runs/<run_id>", methods=["GET"])
def read_run(run_id):
    ctx = guard(ALL_ROLES, read_body=False)
    run = domain.get_run(run_id)
    scope(ctx, domain.run_client_id(run))
    return respond(domain.serialize(run))


@bp.route("/bottling-runs", methods=["GET"])
def list_runs():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.runs.values(), ctx, domain.serialize,
                    owner_fn=domain.run_client_id,
                    filters=(("lot_id", "lot_id"), ("line_id", "line_id"),
                             ("status", "status")))


@bp.route("/bottling-runs/<run_id>/transitions", methods=["POST"])
def run_transitions(run_id):
    ctx = guard([CELLAR_SUPERVISOR], RUN_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(RUN_ACTIONS))

    cases_actual = None
    if action == "COMPLETE":
        cases_actual = v_int(body, "cases_actual", ge=1)

    run = domain.get_run(run_id)
    scope(ctx, domain.run_client_id(run))

    if action == "RESERVE_SUPPLIES":
        declared(run["status"] == "SCHEDULED")
        _reserve_supplies(run)
    elif action == "COMPLETE":
        declared(run["status"] == "SUPPLIES_RESERVED")
        if cases_actual > run["cases_planned"]:
            bad("Field 'cases_actual' may not exceed 'cases_planned'.")
        _complete(run, cases_actual)
    else:  # CANCEL
        declared(run["status"] in LIVE_RUN_STATUSES)
        _cancel(run)

    return respond(domain.serialize(run))


def _reserve_supplies(run):
    lot = db.lots.get(run["lot_id"])
    client_id = domain.lot_client_id(lot) if lot else None
    if client_id is None:
        raise ApiError(ERR_CROSS_CONTRACT_REFERENCE,
                       "The run's lot does not resolve to a client.")

    required = calc.dry_goods_requirement(run["cases_planned"], run["bottle_size_ml"])
    draw = []
    for item_type in ("BOTTLE", "CORK", "CAPSULE", "LABEL", "CASE_BOX"):
        remaining = required[item_type]
        if remaining <= 0:
            continue
        candidates = [i for i in db.dry_goods.values()
                      if i["client_id"] == client_id
                      and i["item_type"] == item_type
                      and i["available_units"] > 0]
        candidates.sort(key=lambda i: (-i["available_units"], sort_key(i)))
        for item in candidates:
            take = min(item["available_units"], remaining)
            if take > 0:
                draw.append({
                    "dry_goods_item_id": item["id"],
                    "item_type": item_type,
                    "units_reserved": take,
                })
                remaining -= take
            if remaining == 0:
                break
        # Rung 80 -- all-or-nothing across every required item type.
        if remaining > 0:
            raise ApiError(ERR_DRY_GOODS_SHORTAGE,
                           "The client's pool cannot cover the required %s units."
                           % item_type)

    for entry in draw:
        item = db.dry_goods[entry["dry_goods_item_id"]]
        item["reserved_units"] = item["reserved_units"] + entry["units_reserved"]
        domain.recompute_dry_goods(item)
        touch(item)

    run["supply_reservations"] = draw
    run["status"] = "SUPPLIES_RESERVED"
    touch(run)


def _complete(run, cases_actual):
    lot = db.lots.get(run["lot_id"])
    consumed = calc.gallons_consumed(cases_actual, run["bottle_size_ml"])

    # Rung 78 -- the lot must still hold that much wine.
    if lot is None or D(lot["volume_gallons"]) < consumed:
        raise ApiError(ERR_INSUFFICIENT_LOT_VOLUME,
                       "The lot no longer holds the wine this run would draw.")

    now = db.now()
    run["cases_actual"] = cases_actual
    run["gallons_consumed"] = consumed

    for entry in run["supply_reservations"]:
        item = db.dry_goods.get(entry["dry_goods_item_id"])
        if item is None:
            continue
        item["on_hand_units"] = item["on_hand_units"] - entry["units_reserved"]
        item["reserved_units"] = item["reserved_units"] - entry["units_reserved"]
        domain.recompute_dry_goods(item)
        touch(item)

    # HOP 1 -- draw the wine down.
    lot["volume_gallons"] = rhu(D(lot["volume_gallons"]) - consumed, 2)
    lot["cases_bottled"] = lot["cases_bottled"] + cases_actual
    touch(lot)

    # HOP 2 -- a lot emptied by the run moves AGING -> BOTTLED.
    if D(lot["volume_gallons"]) == 0 and lot["production_status"] == "AGING":
        lot["production_status"] = "BOTTLED"
        lot["current_vessel_id"] = None
        touch(lot)
        # HOP 3 -- the lot leaves its vessel by itself.
        domain.cascade_lot_left_vessel(lot)

    run["status"] = "COMPLETED"
    run["_completed_dt"] = now
    touch(run)

    client = db.clients.get(domain.lot_client_id(lot))
    if client is not None:
        touch(client)


def _cancel(run):
    if run["status"] == "SUPPLIES_RESERVED":
        # COMPENSATION -- every reserved unit goes back on the shelf.
        for entry in run["supply_reservations"]:
            item = db.dry_goods.get(entry["dry_goods_item_id"])
            if item is None:
                continue
            item["reserved_units"] = item["reserved_units"] - entry["units_reserved"]
            domain.recompute_dry_goods(item)
            touch(item)
        run["supply_reservations"] = []
    run["status"] = "CANCELLED"
    touch(run)
