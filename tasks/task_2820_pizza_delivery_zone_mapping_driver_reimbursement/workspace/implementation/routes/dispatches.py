"""Route construction, commitment, the road and settlement (PRD 3.7-3.9, 3.11)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import listing
import response
import serialize
import validate
from errors import fail

bp = Blueprint("dispatches", __name__)

DISPATCH_STATUSES = ("DRAFT", "STACKED", "LOCKED", "EN_ROUTE", "RETURNED", "SETTLED", "RECALLED", "CANCELLED")
STOP_STATUSES = ("PENDING", "DELIVERED", "RELEASED", "REMADE")
LINE_TYPES = ("PROVISIONAL_STOP", "ACTUAL_STOP", "CLAWBACK")
LINE_STATUSES = ("PROVISIONAL", "ACCRUED", "SUPERSEDED", "VOIDED")
DISPATCH_READ_ROLES = ("StoreManager", "Dispatcher", "Driver", "ComplianceOfficer")
LINE_READ_ROLES = ("StoreManager", "Driver", "ComplianceOfficer")


def _store_of(dispatch):
    return derive.dispatch_store(dispatch)


def _leg_minutes(dispatch, counted):
    """Each counted stop's outbound leg, rounded UP per leg (PRD 3.8)."""
    store = _store_of(dispatch)
    version = derive.in_force_zone_version(store["id"]) if store else None
    legs = []
    for stop in counted:
        if version is not None:
            legs.append(
                calc.ceil_minutes(Decimal(str(stop["planned_miles"])) * version["minutes_per_mile"])
            )
        else:
            legs.append(stop["planned_drive_minutes"] or 0)
    return legs


def _select_cost_model(dispatch, driver):
    candidates = [
        m
        for m in db.cost_models.values()
        if m["store_id"] == driver["store_id"]
        and m["vehicle_class"] == driver["vehicle_class"]
        and m["status"] == "ACTIVE"
        and m["effective_from"] <= dispatch["planned_depart_at"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (m["effective_from"], m["created_at"], m["_seq"]))
    return candidates[-1]


def _estimated_amounts(dispatch, model):
    counted = derive.counted_stops(dispatch["id"])
    total, per_stop = calc.waterfall([s["planned_miles"] for s in counted], model)
    return counted, total, per_stop


@bp.post("/store-ops/dispatches")
def open_dispatch():
    auth.authenticate(["Dispatcher"])
    body = validate.body()
    raw_driver_id = body.get("driver_id")
    driver = None
    if isinstance(raw_driver_id, str) and raw_driver_id != "":
        driver = auth.body_fk("driver", raw_driver_id)
    validate.string(body, "driver_id")
    planned_depart_at = validate.instant(body, "planned_depart_at")
    record = {
        "driver_id": driver["id"],
        "planned_depart_at": planned_depart_at,
        "status": "DRAFT",
        "stop_count": 0,
        "route_minutes": None,
        "expected_return_at": None,
        "resolved_cost_model_id": None,
        "estimated_reimbursement_cents": None,
        "actual_reimbursement_cents": None,
        "reimbursement_variance_cents": None,
        "departed_at": None,
        "returned_at": None,
        "recalled_reason": None,
    }
    db.insert(db.dispatches, record)
    return response.created(serialize.dispatch(record))


@bp.post("/store-ops/dispatches/<dispatch_id>/stops")
def stack_stop(dispatch_id):
    actor = auth.authenticate(["Dispatcher"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    body = validate.body()
    raw_order_id = body.get("order_id")
    order = None
    if isinstance(raw_order_id, str) and raw_order_id != "":
        order = auth.body_fk("order", raw_order_id)
    validate.string(body, "order_id")
    hot_bag_slots = validate.integer(
        body, "hot_bag_slots", required=False, default=1, minimum=1, maximum=2
    )
    if dispatch["status"] not in ("DRAFT", "STACKED"):
        fail("ERR_INVALID_DISPATCH_STATE", "A stop is stacked only onto a DRAFT or STACKED route.")
    driver = db.drivers.get(dispatch["driver_id"])
    store = db.stores.get(driver["store_id"]) if driver else None
    if store is None or order["store_id"] != store["id"]:
        fail("ERR_ORDER_STORE_MISMATCH", "The order belongs to a different store than the driver.")
    if dispatch["stop_count"] + 1 > store["max_stacked_stops"]:
        fail("ERR_STACK_LIMIT_EXCEEDED", "The route is already at the store's stacking cap.")
    if order["fulfillment_status"] != "READY":
        fail("ERR_ORDER_NOT_READY", "Only a READY order can be stacked.")
    for stop in db.stops.values():
        if stop["order_id"] == order["id"] and stop["status"] == "PENDING":
            fail("ERR_ORDER_ALREADY_STACKED", "That order already sits on a live route.")
    address = db.service_addresses.get(order["service_address_id"])
    planned_miles = address["grid_miles"] if address else Decimal("0.00")
    version = derive.pricing_zone_version(address) if address else None
    minutes_per_mile = version["minutes_per_mile"] if version else 0
    ever = [s for s in db.stops.values() if s["dispatch_id"] == dispatch["id"]]
    record = {
        "dispatch_id": dispatch["id"],
        "order_id": order["id"],
        "sequence": len(ever) + 1,
        "hot_bag_slots": hot_bag_slots,
        "planned_miles": planned_miles,
        "planned_drive_minutes": calc.ceil_minutes(Decimal(str(planned_miles)) * minutes_per_mile),
        "actual_miles": None,
        "status": "PENDING",
        "arrived_at": None,
        "cash_collected_cents": 0,
    }
    db.insert(db.stops, record)
    dispatch["stop_count"] = dispatch["stop_count"] + 1
    if dispatch["status"] == "DRAFT":
        dispatch["status"] = "STACKED"
    db.touch(dispatch)
    order["fulfillment_status"] = "ASSIGNED"
    db.touch(order)
    return response.created(serialize.dispatch_stop(record))


@bp.delete("/store-ops/dispatches/<dispatch_id>/stops/<dispatch_stop_id>")
def unstack_stop(dispatch_id, dispatch_stop_id):
    actor = auth.authenticate(["Dispatcher"])
    dispatch, stop = auth.guard(
        actor, [("dispatch", dispatch_id), ("dispatch_stop", dispatch_stop_id)]
    )
    if stop["status"] != "PENDING":
        fail("ERR_INVALID_STOP_STATE", "Only a PENDING stop can be un-stacked.")
    if dispatch["status"] != "STACKED":
        fail("ERR_INVALID_DISPATCH_STATE", "Un-stacking requires a STACKED route.")
    stop["status"] = "RELEASED"
    db.touch(stop)
    order = db.orders.get(stop["order_id"])
    if order is not None and order["fulfillment_status"] == "ASSIGNED":
        order["fulfillment_status"] = "READY"
        db.touch(order)
    dispatch["stop_count"] = dispatch["stop_count"] - 1
    if dispatch["stop_count"] <= 0:
        dispatch["stop_count"] = 0
        dispatch["status"] = "DRAFT"
    db.touch(dispatch)
    # A successful un-stack returns the parent route rather than the removed stop.
    return response.ok(serialize.dispatch(dispatch))


@bp.post("/store-ops/dispatches/<dispatch_id>/lock")
def lock_dispatch(dispatch_id):
    actor = auth.authenticate(["Dispatcher"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    if dispatch["status"] not in ("DRAFT", "STACKED"):
        fail("ERR_INVALID_DISPATCH_STATE", "A route is committed from DRAFT or STACKED.")
    driver = db.drivers.get(dispatch["driver_id"])
    store = _store_of(dispatch)
    if driver is None or driver["qualification_status"] != "QUALIFIED":
        fail("ERR_DRIVER_NOT_QUALIFIED", "The route's driver is not QUALIFIED.")
    if not derive.insurance_covers(driver["id"], dispatch["planned_depart_at"]):
        fail("ERR_INSURANCE_NOT_ACTIVE", "No verified certificate covers the planned departure.")
    model = _select_cost_model(dispatch, driver)
    if model is None:
        fail("ERR_NO_COST_MODEL", "No reimbursement schedule is eligible for this route.")
    counted = derive.counted_stops(dispatch["id"])
    minutes = calc.route_minutes(_leg_minutes(dispatch, counted), store["handoff_minutes_per_stop"])
    expected_return_at = dispatch["planned_depart_at"] + timedelta(minutes=minutes)
    buffer_minutes = timedelta(minutes=store["dispatch_reset_buffer_minutes"])
    own_start = dispatch["planned_depart_at"]
    own_end = expected_return_at + buffer_minutes
    for other in db.dispatches.values():
        if other["id"] == dispatch["id"] or other["driver_id"] != dispatch["driver_id"]:
            continue
        if other["status"] not in ("LOCKED", "EN_ROUTE") or other["expected_return_at"] is None:
            continue
        other_start = other["planned_depart_at"]
        other_end = other["expected_return_at"] + buffer_minutes
        # The driver-occupation interval is closed at both ends.
        if own_start <= other_end and other_start <= own_end:
            fail("ERR_DRIVER_WINDOW_CONFLICT", "The driver is already occupied over that interval.")
    own_slots = derive.committed_hot_bag_slots(dispatch)
    reserved = 0
    for other in db.dispatches.values():
        if other["id"] == dispatch["id"]:
            continue
        if other["status"] not in ("LOCKED", "EN_ROUTE") or other["expected_return_at"] is None:
            continue
        other_store = _store_of(other)
        if other_store is None or other_store["id"] != store["id"]:
            continue
        # The hot-bag reservation window is half-open.
        if own_start < other["expected_return_at"] and other["planned_depart_at"] < expected_return_at:
            reserved += derive.committed_hot_bag_slots(other)
    if reserved + own_slots > store["hot_bag_count"]:
        fail("ERR_HOT_BAG_CAPACITY_EXCEEDED", "The store's insulated-bag pool cannot cover this route.")
    if not counted:
        fail("ERR_DISPATCH_HAS_NO_STOPS", "An empty route has nothing to reimburse.")
    for stop in counted:
        order = db.orders.get(stop["order_id"])
        if order is None or order["settlement_status"] not in ("DISCLOSED", "CHARGED"):
            fail("ERR_FEE_NOT_DISCLOSED", "Every ticket on the route must have been disclosed.")
    total, _per_stop = calc.waterfall([s["planned_miles"] for s in counted], model)
    dispatch["status"] = "LOCKED"
    dispatch["route_minutes"] = minutes
    dispatch["expected_return_at"] = expected_return_at
    dispatch["resolved_cost_model_id"] = model["id"]
    dispatch["estimated_reimbursement_cents"] = total
    db.touch(dispatch)
    return response.ok(serialize.dispatch(dispatch))


@bp.post("/store-ops/dispatches/<dispatch_id>/unlock")
def unlock_dispatch(dispatch_id):
    actor = auth.authenticate(["Dispatcher"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    if dispatch["status"] != "LOCKED":
        fail("ERR_INVALID_DISPATCH_STATE", "Only a LOCKED route can be released.")
    dispatch["status"] = "STACKED"
    dispatch["route_minutes"] = None
    dispatch["expected_return_at"] = None
    dispatch["resolved_cost_model_id"] = None
    dispatch["estimated_reimbursement_cents"] = None
    db.touch(dispatch)
    return response.ok(serialize.dispatch(dispatch))


@bp.post("/store-ops/dispatches/<dispatch_id>/depart")
def depart_dispatch(dispatch_id):
    actor = auth.authenticate(["Driver"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    if dispatch["status"] != "LOCKED":
        fail("ERR_INVALID_DISPATCH_STATE", "Departure is declared only from LOCKED.")
    driver = db.drivers.get(dispatch["driver_id"])
    store = _store_of(dispatch)
    if driver is None or driver["qualification_status"] != "QUALIFIED":
        fail("ERR_DRIVER_NOT_QUALIFIED", "The driver is no longer QUALIFIED.")
    if not derive.insurance_covers(driver["id"], clock.now()):
        fail("ERR_INSURANCE_NOT_ACTIVE", "No verified certificate covers the current instant.")
    if derive.driver_cash_on_hand(driver["id"]) >= store["cash_limit_cents"]:
        fail("ERR_CASH_LIMIT_REACHED", "The driver must visit the safe before leaving again.")
    dispatch["status"] = "EN_ROUTE"
    dispatch["departed_at"] = clock.now()
    db.touch(dispatch)
    pending = [
        s for s in db.stops.values() if s["dispatch_id"] == dispatch["id"] and s["status"] == "PENDING"
    ]
    for stop in db.ordered(pending):
        order = db.orders.get(stop["order_id"])
        if order is not None and order["fulfillment_status"] == "ASSIGNED":
            order["fulfillment_status"] = "EN_ROUTE"
            db.touch(order)
    return response.ok(serialize.dispatch(dispatch))


@bp.post("/store-ops/dispatches/<dispatch_id>/stops/<dispatch_stop_id>/door-arrival")
def door_arrival(dispatch_id, dispatch_stop_id):
    actor = auth.authenticate(["Driver"])
    dispatch, stop = auth.guard(
        actor, [("dispatch", dispatch_id), ("dispatch_stop", dispatch_stop_id)]
    )
    body = validate.body()
    actual_miles = validate.miles(body, "actual_miles", required=False, minimum="0")
    order = db.orders.get(stop["order_id"])
    cash_supplied = body.get("cash_collected_cents")
    cash_collected = validate.integer(body, "cash_collected_cents", required=False)
    if order is not None and order["payment_method"] == "CASH":
        if cash_supplied is None or cash_collected != order["total_charge_cents"]:
            fail(
                "ERR_INVALID_REQUEST",
                "A cash door arrival must carry cash_collected_cents equal to the order total.",
            )
    elif cash_supplied is not None and cash_collected != 0:
        fail("ERR_INVALID_REQUEST", "A card order takes no cash at the door.")
    if stop["status"] != "PENDING":
        fail("ERR_INVALID_STOP_STATE", "Only a PENDING stop records a handoff.")
    if dispatch["status"] != "EN_ROUTE":
        fail("ERR_INVALID_DISPATCH_STATE", "The route must be EN_ROUTE.")
    if order is None or order["fulfillment_status"] != "EN_ROUTE":
        fail("ERR_INVALID_ORDER_STATE", "The stop's order must be EN_ROUTE.")
    driver = db.drivers.get(dispatch["driver_id"])
    store = _store_of(dispatch)
    is_cash = order["payment_method"] == "CASH"
    if actual_miles is not None:
        stop["actual_miles"] = actual_miles
    stop["cash_collected_cents"] = order["total_charge_cents"] if is_cash else 0
    stop["arrived_at"] = clock.now()
    stop["status"] = "DELIVERED"
    db.touch(stop)
    order["fulfillment_status"] = "DELIVERED"
    order["door_arrival_at"] = clock.now()
    gross = clock.elapsed_minutes_floor(order["door_arrival_at"], order["placed_at"])
    gross, net = calc.order_to_door(
        gross, order["zone_hold_minutes"], order["remake_hold_minutes"]
    )
    order["order_to_door_gross_minutes"] = gross
    order["order_to_door_net_minutes"] = net
    if order["settlement_status"] == "DISCLOSED":
        order["settlement_status"] = "CHARGED"
    order["cash_collected_cents"] = order["total_charge_cents"] if is_cash else 0
    db.touch(order)
    if is_cash:
        if driver is not None:
            db.touch(driver)
        if store is not None:
            db.touch(store)
    model = db.cost_models.get(dispatch["resolved_cost_model_id"])
    if model is not None:
        counted, _total, per_stop = _estimated_amounts(dispatch, model)
        amount = 0
        for index, candidate in enumerate(counted):
            if candidate["id"] == stop["id"]:
                amount = per_stop[index]
        line = {
            "dispatch_id": dispatch["id"],
            "driver_id": dispatch["driver_id"],
            "order_id": order["id"],
            "line_type": "PROVISIONAL_STOP",
            "basis": "ESTIMATED",
            "amount_cents": amount,
            "sequence_snapshot": stop["sequence"],
            "status": "PROVISIONAL",
        }
        db.insert(db.lines, line)
    return response.ok(serialize.dispatch_stop(stop))


@bp.post("/store-ops/dispatches/<dispatch_id>/return")
def return_dispatch(dispatch_id):
    actor = auth.authenticate(["Driver"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    if dispatch["status"] != "EN_ROUTE":
        fail("ERR_INVALID_DISPATCH_STATE", "Check-in is declared only from EN_ROUTE.")
    for stop in derive.dispatch_stops(dispatch["id"]):
        if stop["status"] not in ("DELIVERED", "RELEASED", "REMADE"):
            fail("ERR_STOPS_OUTSTANDING", "A pizza is still in the bag.")
    dispatch["status"] = "RETURNED"
    dispatch["returned_at"] = clock.now()
    db.touch(dispatch)
    return response.ok(serialize.dispatch(dispatch))


@bp.post("/store-ops/dispatches/<dispatch_id>/settle")
def settle_dispatch(dispatch_id):
    actor = auth.authenticate(["StoreManager"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    if dispatch["status"] != "RETURNED":
        fail("ERR_INVALID_DISPATCH_STATE", "Settlement is declared only from RETURNED.")
    paid = [s for s in derive.dispatch_stops(dispatch["id"]) if s["status"] in ("DELIVERED", "REMADE")]
    for stop in paid:
        if stop["actual_miles"] is None:
            fail("ERR_ODOMETER_MISSING", "Every paid stop needs an odometer reading.")
    model = db.cost_models.get(dispatch["resolved_cost_model_id"])
    if model is None:
        fail("ERR_NO_COST_MODEL", "The route carries no snapshotted reimbursement schedule.")
    total, per_stop = calc.waterfall([s["actual_miles"] for s in paid], model)
    provisional = [
        line
        for line in db.lines.values()
        if line["dispatch_id"] == dispatch["id"] and line["line_type"] == "PROVISIONAL_STOP"
    ]
    for line in db.ordered(provisional):
        line["status"] = "SUPERSEDED"
        db.touch(line)
    for index, stop in enumerate(paid):
        db.insert(
            db.lines,
            {
                "dispatch_id": dispatch["id"],
                "driver_id": dispatch["driver_id"],
                "order_id": stop["order_id"],
                "line_type": "ACTUAL_STOP",
                "basis": "ACTUAL",
                "amount_cents": per_stop[index],
                "sequence_snapshot": stop["sequence"],
                "status": "ACCRUED",
            },
        )
    dispatch["status"] = "SETTLED"
    dispatch["actual_reimbursement_cents"] = total
    dispatch["reimbursement_variance_cents"] = total - (
        dispatch["estimated_reimbursement_cents"] or 0
    )
    db.touch(dispatch)
    driver = db.drivers.get(dispatch["driver_id"])
    if driver is not None:
        db.touch(driver)
    orders = []
    for stop in derive.dispatch_stops(dispatch["id"]):
        order = db.orders.get(stop["order_id"])
        if order is not None and order["fulfillment_status"] == "DELIVERED":
            orders.append(order)
    for order in db.ordered(orders):
        order["fulfillment_status"] = "CLOSED"
        if order["settlement_status"] in ("CHARGED", "ADJUSTED"):
            order["settlement_status"] = "CLOSED_SETTLED"
        db.touch(order)
    return response.ok(serialize.dispatch(dispatch))


@bp.post("/store-ops/dispatches/<dispatch_id>/recall")
def recall_dispatch(dispatch_id):
    actor = auth.authenticate(["StoreManager", "Dispatcher"])
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    body = validate.body()
    recalled_reason = validate.string(body, "recalled_reason")
    if dispatch["status"] not in ("DRAFT", "STACKED", "LOCKED", "EN_ROUTE"):
        fail("ERR_INVALID_DISPATCH_STATE", "This route can no longer be recalled.")
    if dispatch["status"] == "DRAFT" and dispatch["stop_count"] == 0:
        dispatch["status"] = "CANCELLED"
        dispatch["recalled_reason"] = recalled_reason
        db.touch(dispatch)
    else:
        cascade.recall_dispatch(dispatch, recalled_reason)
    return response.ok(serialize.dispatch(dispatch))


@bp.get("/store-ops/dispatches/<dispatch_id>")
def read_dispatch(dispatch_id):
    actor = auth.authenticate(DISPATCH_READ_ROLES)
    (dispatch,) = auth.guard(actor, [("dispatch", dispatch_id)])
    return response.ok(serialize.dispatch(dispatch))


@bp.get("/store-ops/dispatches")
def list_dispatches():
    actor = auth.authenticate(DISPATCH_READ_ROLES)
    driver_id = validate.filter_string("driver_id")
    cost_model_id = validate.filter_string("resolved_cost_model_id")
    status = validate.filter_enum("status", DISPATCH_STATUSES)
    records = list(db.dispatches.values())
    if actor.is_manager:
        records = [d for d in records if auth.owning_store_id("dispatch", d) == actor.user_id]
    elif actor.is_driver:
        records = [d for d in records if d["driver_id"] == actor.user_id]
    if driver_id is not None:
        records = [d for d in records if d["driver_id"] == driver_id]
    if cost_model_id is not None:
        records = [d for d in records if d["resolved_cost_model_id"] == cost_model_id]
    if status is not None:
        records = [d for d in records if d["status"] == status]
    return listing.respond(records, serialize.dispatch)


@bp.get("/store-ops/dispatch-stops/<dispatch_stop_id>")
def read_stop(dispatch_stop_id):
    actor = auth.authenticate(DISPATCH_READ_ROLES)
    (stop,) = auth.guard(actor, [("dispatch_stop", dispatch_stop_id)])
    return response.ok(serialize.dispatch_stop(stop))


@bp.get("/store-ops/dispatch-stops")
def list_stops():
    actor = auth.authenticate(DISPATCH_READ_ROLES)
    dispatch_id = validate.filter_string("dispatch_id")
    order_id = validate.filter_string("order_id")
    status = validate.filter_enum("status", STOP_STATUSES)
    records = list(db.stops.values())
    if actor.is_manager:
        records = [s for s in records if auth.owning_store_id("dispatch_stop", s) == actor.user_id]
    elif actor.is_driver:
        records = [s for s in records if auth.owning_driver_id("dispatch_stop", s) == actor.user_id]
    if dispatch_id is not None:
        records = [s for s in records if s["dispatch_id"] == dispatch_id]
    if order_id is not None:
        records = [s for s in records if s["order_id"] == order_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    if dispatch_id is not None:
        # Scoping by route walks it in sequence ascending.
        return listing.respond(records, serialize.dispatch_stop, key=lambda s: s["sequence"])
    return listing.respond(records, serialize.dispatch_stop)


@bp.get("/store-ops/reimbursement-lines/<reimbursement_line_id>")
def read_line(reimbursement_line_id):
    actor = auth.authenticate(LINE_READ_ROLES)
    (line,) = auth.guard(actor, [("reimbursement_line", reimbursement_line_id)])
    return response.ok(serialize.reimbursement_line(line))


@bp.get("/store-ops/reimbursement-lines")
def list_lines():
    actor = auth.authenticate(LINE_READ_ROLES)
    dispatch_id = validate.filter_string("dispatch_id")
    driver_id = validate.filter_string("driver_id")
    order_id = validate.filter_string("order_id")
    line_type = validate.filter_enum("line_type", LINE_TYPES)
    status = validate.filter_enum("status", LINE_STATUSES)
    records = list(db.lines.values())
    if actor.is_manager:
        records = [
            line for line in records
            if auth.owning_store_id("reimbursement_line", line) == actor.user_id
        ]
    elif actor.is_driver:
        records = [line for line in records if line["driver_id"] == actor.user_id]
    if dispatch_id is not None:
        records = [line for line in records if line["dispatch_id"] == dispatch_id]
    if driver_id is not None:
        records = [line for line in records if line["driver_id"] == driver_id]
    if order_id is not None:
        records = [line for line in records if line["order_id"] == order_id]
    if line_type is not None:
        records = [line for line in records if line["line_type"] == line_type]
    if status is not None:
        records = [line for line in records if line["status"] == status]
    return listing.respond(records, serialize.reimbursement_line)
