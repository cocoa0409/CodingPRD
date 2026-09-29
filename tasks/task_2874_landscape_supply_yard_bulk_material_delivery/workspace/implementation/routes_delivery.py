"""Delivery trucks and the delivery-load run (plan, dispatch, deliver, ...)."""
from flask import Blueprint

import calc
import serial
from core import (
    D, arg, auth, body, contractor_filter, db, epoch_seconds, fail, new_record,
    opt_num, present, r2, render_list, req_bool, req_enum, req_id, req_instant,
    req_num, req_str, require, respond, scope_via_order, touch,
)

bp = Blueprint("delivery", __name__)

AXLE_CLASSES = ("SINGLE", "TANDEM", "TRI_AXLE")
ACCESS_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
TRUCK_STATUSES = ("AVAILABLE", "IN_SERVICE", "OUT_OF_SERVICE")
REFUSAL_REASONS = ("ACCESS_BLOCKED", "CUSTOMER_REFUSED", "EQUIPMENT_FAILURE")
LIVE_LOAD_STATUSES = ("PLANNED", "DISPATCHED")


# --------------------------------------------------------------------------
# Fleet
# --------------------------------------------------------------------------
@bp.post("/delivery-trucks")
def create_truck():
    auth("DispatchPlanner")
    data = body()
    truck_code = req_str(data, "truck_code")
    axle_class = req_enum(data, "axle_class", AXLE_CLASSES)
    max_payload = req_num(data, "max_payload_lb", minimum=0, exclusive_min=True)
    bed_capacity = req_num(data, "bed_capacity_cubic_yards", minimum=0,
                           exclusive_min=True)
    min_access = req_enum(data, "min_driveway_access_class", ACCESS_CLASSES)
    record = new_record(
        truck_code=truck_code,
        axle_class=axle_class,
        max_payload_lb=max_payload,
        bed_capacity_cubic_yards=bed_capacity,
        min_driveway_access_class=min_access,
        status="AVAILABLE",
    )
    db.insert("delivery_trucks", record)
    return respond(serial.delivery_truck(record), 201)


@bp.get("/delivery-trucks")
def list_trucks():
    auth("DispatchPlanner", "YardAdmin", "YardLoader")
    axle_class = arg("axle_class")
    status = arg("status")
    min_access = arg("min_driveway_access_class")
    rows = []
    for record in db.delivery_trucks.values():
        if axle_class is not None and record["axle_class"] != axle_class:
            continue
        if status is not None and record["status"] != status:
            continue
        if min_access is not None and record["min_driveway_access_class"] != min_access:
            continue
        rows.append(record)
    return render_list(rows, serial.delivery_truck)


@bp.get("/delivery-trucks/<delivery_truck_id>")
def read_truck(delivery_truck_id):
    auth("DispatchPlanner", "YardAdmin", "YardLoader")
    record = require(db.get("delivery_trucks", delivery_truck_id), "delivery_trucks")
    return respond(serial.delivery_truck(record))


@bp.patch("/delivery-trucks/<delivery_truck_id>")
def patch_truck(delivery_truck_id):
    auth("DispatchPlanner")
    data = body()
    status = None
    if present(data, "status"):
        status = req_enum(data, "status", TRUCK_STATUSES)
    record = require(db.get("delivery_trucks", delivery_truck_id), "delivery_trucks")
    if status is not None:
        record["status"] = status
    touch(record)
    return respond(serial.delivery_truck(record))


# --------------------------------------------------------------------------
# Load planning gates (PRD 3.5, ladder rungs 20, 21, 23, 24 and 30)
# --------------------------------------------------------------------------
def _access_rank(access_class):
    return calc.ACCESS_RANK.get(access_class)


def _fit_gates(order, truck, planned_cy):
    """Weight, access and capacity gates in the ladder's pinned order."""
    material = calc.pinned_material_for_order(order)
    payload, max_allowed = calc.load_fit(planned_cy, truck, material,
                                         order.get("driveway_access_class"))
    if payload is not None and D(payload) > D(truck["max_payload_lb"]):
        fail("ERR_AXLE_WEIGHT_LIMIT_EXCEEDED",
             "The planned payload exceeds the truck's legal weight.")
    site_rank = _access_rank(order.get("driveway_access_class"))
    truck_rank = _access_rank(truck["min_driveway_access_class"])
    if site_rank is not None and truck_rank is not None and site_rank < truck_rank:
        fail("ERR_DRIVEWAY_ACCESS_RESTRICTED",
             "The truck may not enter this driveway grade.")
    ceilings = [D(truck["bed_capacity_cubic_yards"])]
    cap = calc.driveway_cap(order.get("driveway_access_class"))
    if cap is not None:
        ceilings.append(D(cap))
    if D(planned_cy) > min(ceilings):
        fail("ERR_LOAD_EXCEEDS_TRUCK_CAPACITY",
             "The planned volume exceeds the truck or driveway ceiling.")
    return payload, max_allowed


def _window_conflict(truck_id, start, end, exclude_load_id=None):
    buffer_seconds = calc.TURNAROUND_BUFFER_SECONDS
    new_start = epoch_seconds(start)
    new_end = epoch_seconds(end)
    for load in db.rows("delivery_loads"):
        if load["id"] == exclude_load_id:
            continue
        if load["delivery_truck_id"] != truck_id:
            continue
        if load["status"] not in LIVE_LOAD_STATUSES:
            continue
        other_start = epoch_seconds(load["window_start"])
        other_end = epoch_seconds(load["window_end"])
        if (new_start < other_end + buffer_seconds
                and other_start < new_end + buffer_seconds):
            fail("ERR_TRUCK_WINDOW_CONFLICT",
                 "The truck is already booked over this window.")


def _order_planning_headroom(order, exclude_load_id=None):
    headroom = calc.outstanding_bulk_balance(order)
    for load in calc.loads_of(order["id"]):
        if load["id"] == exclude_load_id:
            continue
        if load["status"] in LIVE_LOAD_STATUSES:
            headroom -= D(load["planned_cubic_yards"])
    return headroom


# --------------------------------------------------------------------------
# Delivery loads
# --------------------------------------------------------------------------
@bp.post("/delivery-loads")
def create_load():
    auth("DispatchPlanner")
    data = body()
    order_id = req_id(data, "material_order_id")
    truck_id = req_id(data, "delivery_truck_id")
    planned = req_num(data, "planned_cubic_yards", minimum=0, exclusive_min=True)
    window_start = req_instant(data, "window_start")
    window_end = req_instant(data, "window_end")

    order = require(db.get("material_orders", order_id), "material_orders")
    truck = require(db.get("delivery_trucks", truck_id), "delivery_trucks")

    if order["fulfillment_status"] not in ("CONFIRMED", "ALLOCATED"):
        fail("ERR_ORDER_NOT_ALLOCATABLE",
             "Order is %s." % order["fulfillment_status"])
    if truck["status"] != "AVAILABLE":
        fail("ERR_TRUCK_UNAVAILABLE", "Truck is %s." % truck["status"])

    payload, max_allowed = _fit_gates(order, truck, planned)
    _window_conflict(truck_id, window_start, window_end)
    if order["fulfillment_mode"] != "DELIVERY":
        fail("ERR_DELIVERY_MODE_REQUIRED",
             "Only a DELIVERY order may carry a truck load.")
    if window_end <= window_start:
        fail("ERR_INVALID_WINDOW", "window_end must be after window_start.")
    if D(planned) > _order_planning_headroom(order):
        fail("ERR_LOAD_EXCEEDS_ORDER_BALANCE",
             "The planned volume exceeds the order's undelivered balance.")

    lot = calc.pinned_lot_for_order(order)
    record = new_record(
        material_order_id=order_id,
        delivery_truck_id=truck_id,
        inventory_lot_id=None if lot is None else lot["id"],
        planned_cubic_yards=planned,
        window_start=window_start,
        window_end=window_end,
        planned_payload_lb=payload,
        max_allowed_cubic_yards=max_allowed,
        actual_net_cubic_yards=None,
        spillage_cubic_yards=0.0,
        driveway_protection_used=None,
        dispatched_by_user_id=None,
        refusal_reason=None,
        status="PLANNED",
    )
    record["_dispatched_at"] = None
    db.insert("delivery_loads", record)
    calc.evaluate_allocate(order)
    return respond(serial.delivery_load(record), 201)


@bp.get("/delivery-loads")
def list_loads():
    ctx = auth("DispatchPlanner", "YardAdmin", "ClaimsAdjuster", "Contractor")
    order_id = arg("material_order_id")
    truck_id = arg("delivery_truck_id")
    lot_id = arg("inventory_lot_id")
    status = arg("status")
    rows = []
    for record in db.delivery_loads.values():
        if order_id is not None and record["material_order_id"] != order_id:
            continue
        if truck_id is not None and record["delivery_truck_id"] != truck_id:
            continue
        if lot_id is not None and record["inventory_lot_id"] != lot_id:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    rows = contractor_filter(
        ctx, rows,
        lambda r: (db.get("material_orders", r["material_order_id"]) or {}).get(
            "contractor_account_id"))
    return render_list(rows, serial.delivery_load)


@bp.get("/delivery-loads/<delivery_load_id>")
def read_load(delivery_load_id):
    ctx = auth("DispatchPlanner", "YardAdmin", "ClaimsAdjuster", "Contractor",
               "YardLoader")
    record = db.get("delivery_loads", delivery_load_id)
    if record is not None:
        scope_via_order(ctx, db.get("material_orders", record["material_order_id"]))
    require(record, "delivery_loads")
    return respond(serial.delivery_load(record))


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
@bp.post("/delivery-loads/<delivery_load_id>/dispatch")
def dispatch_load(delivery_load_id):
    ctx = auth("DispatchPlanner")
    load = require(db.get("delivery_loads", delivery_load_id), "delivery_loads")
    if load["status"] != "PLANNED":
        fail("ERR_LOAD_NOT_PLANNED", "Load is %s." % load["status"])
    lot = db.get("inventory_lots", load["inventory_lot_id"]) \
        if load["inventory_lot_id"] else None
    if lot is not None and lot["status"] != "AVAILABLE":
        fail("ERR_LOT_QUARANTINED", "The pinned lot is %s." % lot["status"])
    truck = db.get("delivery_trucks", load["delivery_truck_id"])
    if truck is None or truck["status"] != "AVAILABLE":
        fail("ERR_TRUCK_UNAVAILABLE", "The truck is not available.")
    order = db.get("material_orders", load["material_order_id"])
    account = calc.account_of_order(order) if order is not None else None
    if account is None or account["account_status"] != "ACTIVE":
        fail("ERR_ACCOUNT_CREDIT_HOLD", "The buying account is on credit hold.")

    load["status"] = "DISPATCHED"
    load["dispatched_by_user_id"] = ctx.user_id
    load["_dispatched_at"] = db.clock
    touch(load)
    truck["status"] = "IN_SERVICE"
    touch(truck)
    return respond(serial.delivery_load(load))


# --------------------------------------------------------------------------
# Delivery close-out (PRD 3.5, five hops)
# --------------------------------------------------------------------------
@bp.post("/delivery-loads/<delivery_load_id>/deliver")
def deliver_load(delivery_load_id):
    auth("DispatchPlanner")
    data = body()
    actual = req_num(data, "actual_net_cubic_yards", minimum=0)
    protection_used = req_bool(data, "driveway_protection_used")
    spillage = opt_num(data, "spillage_cubic_yards", default=0.0, minimum=0)
    load = require(db.get("delivery_loads", delivery_load_id), "delivery_loads")
    if load["status"] != "DISPATCHED":
        fail("ERR_LOAD_NOT_DISPATCHED", "Load is %s." % load["status"])

    order = db.get("material_orders", load["material_order_id"])
    account = calc.account_of_order(order) if order is not None else None
    if account is not None and account["driveway_protection_required"] \
            and protection_used is not True:
        fail("ERR_DRIVEWAY_PROTECTION_REQUIRED",
             "This account requires driveway protection on every delivery.")
    if D(actual) + D(spillage) > D(load["planned_cubic_yards"]):
        fail("ERR_DELIVERED_EXCEEDS_PLANNED",
             "Delivered plus spilled volume exceeds the planned volume.")

    # ---- hop one -----------------------------------------------------------
    load["actual_net_cubic_yards"] = r2(actual)
    load["spillage_cubic_yards"] = r2(spillage)
    load["driveway_protection_used"] = protection_used
    load["status"] = "DELIVERED"
    touch(load)

    truck = db.get("delivery_trucks", load["delivery_truck_id"])
    if truck is not None and truck["status"] != "AVAILABLE":
        truck["status"] = "AVAILABLE"
        touch(truck)

    lines = calc.lines_of(order["id"])
    before = dict((line["id"], line["version"]) for line in lines)
    calc.distribute_delivered_volume(order, r2(actual))
    instant = load.get("_dispatched_at") or db.clock
    axle_class = truck["axle_class"] if truck is not None else None
    calc.finalize_order_money(order, instant, axle_class)
    calc.collapse_line_versions(lines, before)
    if order["fulfillment_status"] == "ALLOCATED" and calc.order_fully_delivered(order):
        order["fulfillment_status"] = "FULFILLED"
    touch(order)

    lot = db.get("inventory_lots", load["inventory_lot_id"]) \
        if load["inventory_lot_id"] else None
    if lot is not None:
        calc.recompute_lot(lot)
        calc.maybe_deplete_lot(lot)
    calc.recompute_lots_of_order(order)
    calc.create_container_return(order)

    # ---- hops two, three, four and five ------------------------------------
    if order["job_purchase_order_id"]:
        po = db.get("job_purchase_orders", order["job_purchase_order_id"])
        if po is not None:
            calc.recompute_po(po)
    if account is not None:
        calc.recompute_account(account)
        calc.evaluate_credit_posture(account)
    return respond(serial.delivery_load(load))


# --------------------------------------------------------------------------
# Refusal, replanning and cancellation
# --------------------------------------------------------------------------
@bp.post("/delivery-loads/<delivery_load_id>/refuse")
def refuse_load(delivery_load_id):
    auth("DispatchPlanner")
    data = body()
    reason = req_enum(data, "refusal_reason", REFUSAL_REASONS)
    load = require(db.get("delivery_loads", delivery_load_id), "delivery_loads")
    if load["status"] != "DISPATCHED":
        fail("ERR_LOAD_NOT_DISPATCHED", "Load is %s." % load["status"])

    load["status"] = "REFUSED"
    load["refusal_reason"] = reason
    touch(load)
    truck = db.get("delivery_trucks", load["delivery_truck_id"])
    if truck is not None:
        target = "OUT_OF_SERVICE" if reason == "EQUIPMENT_FAILURE" else "AVAILABLE"
        if truck["status"] != target:
            truck["status"] = target
            touch(truck)
    order = db.get("material_orders", load["material_order_id"])
    if order is not None:
        calc.evaluate_revert(order)
        calc.recompute_lots_of_order(order)
    return respond(serial.delivery_load(load))


@bp.post("/delivery-loads/<delivery_load_id>/replan")
def replan_load(delivery_load_id):
    auth("DispatchPlanner")
    data = body()
    truck_id = req_id(data, "delivery_truck_id")
    window_start = req_instant(data, "window_start")
    window_end = req_instant(data, "window_end")
    planned = req_num(data, "planned_cubic_yards", minimum=0, exclusive_min=True)
    load = require(db.get("delivery_loads", delivery_load_id), "delivery_loads")
    truck = require(db.get("delivery_trucks", truck_id), "delivery_trucks")
    if load["status"] != "REFUSED":
        fail("ERR_LOAD_NOT_REFUSED", "Load is %s." % load["status"])
    if truck["status"] != "AVAILABLE":
        fail("ERR_TRUCK_UNAVAILABLE", "Truck is %s." % truck["status"])

    order = db.get("material_orders", load["material_order_id"])
    payload, max_allowed = _fit_gates(order, truck, planned)
    _window_conflict(truck_id, window_start, window_end, exclude_load_id=load["id"])
    if window_end <= window_start:
        fail("ERR_INVALID_WINDOW", "window_end must be after window_start.")

    load["delivery_truck_id"] = truck_id
    load["window_start"] = window_start
    load["window_end"] = window_end
    load["planned_cubic_yards"] = planned
    load["planned_payload_lb"] = payload
    load["max_allowed_cubic_yards"] = max_allowed
    load["refusal_reason"] = None
    load["status"] = "PLANNED"
    touch(load)
    if order is not None:
        calc.evaluate_allocate(order)
    return respond(serial.delivery_load(load))


@bp.post("/delivery-loads/<delivery_load_id>/cancel")
def cancel_load(delivery_load_id):
    auth("DispatchPlanner")
    load = require(db.get("delivery_loads", delivery_load_id), "delivery_loads")
    if load["status"] != "PLANNED":
        fail("ERR_LOAD_NOT_PLANNED", "Load is %s." % load["status"])

    load["status"] = "CANCELLED"
    touch(load)
    truck = db.get("delivery_trucks", load["delivery_truck_id"])
    if truck is not None and truck["status"] != "AVAILABLE":
        truck["status"] = "AVAILABLE"
        touch(truck)
    order = db.get("material_orders", load["material_order_id"])
    if order is not None:
        calc.evaluate_revert(order)
        calc.recompute_lots_of_order(order)
    return respond(serial.delivery_load(load))
