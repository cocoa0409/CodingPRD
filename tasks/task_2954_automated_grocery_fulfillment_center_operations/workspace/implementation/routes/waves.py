"""Wave formation, dock scheduling, the picking floor, totes, retrieval tasks,
consolidation, the loading sequence and dispatch (PRD 3.4, 3.5, 3.7)."""

from flask import Blueprint

import db as store
from db import db
from errors import ApiError
import response as resp
import validation as v
from middleware import endpoint, must_get, actor_id
from services import cascade, derive, money, selectors

bp = Blueprint("waves", __name__)

PLANNER = ["WavePlanner"]
OPERATOR = ["PickOperator"]
WAVE_READERS = ["FulfillmentAdmin", "WavePlanner", "PickOperator"]


def _frozen_gate(wave):
    """Gate step 12."""
    if wave["posture"] == "FROZEN":
        raise ApiError("ERR_WAVE_FROZEN", "the wave's posture is FROZEN")


# --------------------------------------------------------------------------
# Wave formation
# --------------------------------------------------------------------------
@bp.route("/delivery-waves", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def create_wave():
    body = v.read_body()
    route = v.fk(body, "route_id", db.routes, "ERR_ROUTE_NOT_FOUND")
    slot = v.fk(body, "delivery_slot_id", db.slots, "ERR_SLOT_NOT_FOUND")
    data = v.check_body(body, [
        v.f_id("route_id"),
        v.f_id("delivery_slot_id"),
        v.f_str("wave_code", 1, 32),
        v.f_instant("cutoff_at"),
    ])
    v.ensure_unique(db.waves, "wave_code", data["wave_code"])
    if slot["route_id"] != route["id"]:
        v.bad("the delivery slot does not serve the wave's route")
    for existing in db.waves.values():
        if existing["delivery_slot_id"] == slot["id"]:
            v.bad("a wave already exists for this delivery slot")
    if data["cutoff_at"] >= slot["window_start"]:
        v.bad("cutoff_at must be strictly earlier than the slot's window_start")
    wave = store.insert(db.waves, {
        "route_id": route["id"],
        "delivery_slot_id": slot["id"],
        "wave_code": data["wave_code"],
        "cutoff_at": data["cutoff_at"],
        "status": "FORMING",
        "posture": "OPEN",
        "order_count": 0,
        "tote_count": 0,
        "load_sequence": [],
        "transport_cost_cents": None,
        "consolidated_by_user_id": None,
        "dock_bay_id": None,
        "load_start": None,
        "load_end": None,
    })
    # PRD 3.3 enumerates the surge recompute triggers exhaustively -- slot
    # creation, booking creation, booking confirmation, capacity release,
    # capacity withholding, order cancellation and a clock move.  Opening a wave
    # is deliberately absent from that list (only a wave's *status* changes, at
    # start-picking and dispatch, re-price the route's slots), so the stored
    # multiplier is left exactly as it stood.
    return resp.created(wave)


@bp.route("/delivery-waves/<wave_id>", methods=["GET"])
@endpoint(roles=WAVE_READERS)
def read_wave(wave_id):
    return resp.obj(must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND"))


@bp.route("/delivery-waves", methods=["GET"])
@endpoint(roles=WAVE_READERS)
def list_waves():
    items = resp.filtered(list(db.waves.values()), {
        "route_id": "route_id",
        "delivery_slot_id": "delivery_slot_id",
        "dock_bay_id": "dock_bay_id",
        "status": "status",
    })
    return resp.listing(items)


@bp.route("/delivery-waves/<wave_id>/slot-orders", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def slot_orders(wave_id):
    wave = must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND")
    body = v.read_body()
    order = v.fk(body, "customer_order_id", db.orders, "ERR_ORDER_NOT_FOUND")
    v.check_body(body, [v.f_id("customer_order_id")])
    # gate 11
    if wave["status"] != "FORMING":
        raise ApiError("ERR_INVALID_STATE", "orders may only be slotted into a FORMING wave")
    if db.clock >= wave["cutoff_at"]:
        raise ApiError("ERR_INVALID_STATE", "the wave's cutoff has passed")
    if order["fulfillment_status"] != "SLOTTED":
        raise ApiError("ERR_INVALID_STATE", "the order is not SLOTTED")
    # gate 19
    matched = None
    for booking in derive.order_bookings(order):
        if (booking["status"] == "CONFIRMED"
                and booking["delivery_slot_id"] == wave["delivery_slot_id"]):
            matched = booking
            break
    if matched is None:
        raise ApiError(
            "ERR_WAVE_SLOT_MISMATCH",
            "the order holds no CONFIRMED booking on the wave's delivery slot",
        )
    # PRD 3.4 -- the shopper's home route must be the wave's route
    account = db.accounts.get(order["customer_id"])
    if account is None or account["home_route_id"] != wave["route_id"]:
        raise ApiError("ERR_ROUTE_MISMATCH", "the wave does not serve the shopper's home route")

    order["wave_id"] = wave["id"]
    order["fulfillment_status"] = "WAVED"
    store.bump(order)
    derive.recompute_wave_counters(wave)
    derive.recompute_wave_posture(wave)
    return resp.obj(wave)


@bp.route("/delivery-waves/<wave_id>/assign-dock", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def assign_dock(wave_id):
    wave = must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND")
    body = v.read_body()
    bay = v.fk(body, "dock_bay_id", db.bays, "ERR_DOCK_BAY_NOT_FOUND")
    data = v.check_body(body, [
        v.f_id("dock_bay_id"),
        v.f_instant("load_start"),
        v.f_instant("load_end"),
    ])
    if data["load_end"] <= data["load_start"]:
        v.bad("load_end must be strictly after load_start")
    # gate 11
    if wave["status"] != "FORMING":
        raise ApiError("ERR_INVALID_STATE", "a dock is assigned while the wave is FORMING")
    # gate 12
    _frozen_gate(wave)
    # gate 23 -- aggregate concurrency over the half-open interval
    start = data["load_start"]
    end = data["load_end"]
    overlaps = []
    for other in db.waves.values():
        if other["id"] == wave["id"]:
            continue
        if other["dock_bay_id"] != bay["id"]:
            continue
        if other["load_start"] is None or other["load_end"] is None:
            continue
        if other["load_start"] < end and start < other["load_end"]:
            overlaps.append(other)
    instants = [start]
    for other in overlaps:
        if start < other["load_start"] < end:
            instants.append(other["load_start"])
    for instant in instants:
        covering = len([
            o for o in overlaps
            if o["load_start"] <= instant < o["load_end"]
        ])
        if covering >= bay["parallel_van_capacity"]:
            raise ApiError(
                "ERR_DOCK_BAY_CAPACITY_EXCEEDED",
                "the dock bay is already at its parallel van capacity",
            )
    wave["dock_bay_id"] = bay["id"]
    wave["load_start"] = start
    wave["load_end"] = end
    return resp.obj(wave)


# --------------------------------------------------------------------------
# Starting the picking phase
# --------------------------------------------------------------------------
@bp.route("/delivery-waves/<wave_id>/start-picking", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def start_picking(wave_id):
    wave = must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND")
    v.check_body(v.read_body(), [])
    # gate 11
    if wave["status"] != "FORMING":
        raise ApiError("ERR_INVALID_STATE", "only a FORMING wave can start picking")
    # gate 12
    _frozen_gate(wave)
    population = selectors.retrieval_sequence(wave)
    # gate 13 -- every zone entered must be OPERATIONAL
    for line in population:
        sku = db.skus[line["sku_id"]]
        zone = db.zones[sku["grid_zone_id"]]
        if zone["status"] != "OPERATIONAL":
            raise ApiError(
                "ERR_ZONE_NOT_OPERATIONAL",
                "a grid zone serving this wave is not OPERATIONAL",
            )
    # gate 26 -- the wave must have at least one member order
    if len(derive.wave_member_orders(wave)) == 0:
        raise ApiError("ERR_WAVE_HAS_NO_ORDERS", "the wave has no member orders")
    # gate 27 -- a station must be available for every line
    for line in population:
        if selectors.select_station(db.skus[line["sku_id"]]) is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_PICK_STATION", "no pick station can serve this wave"
            )
    # gate 31 -- inventory is tested across all lines of the wave together
    demand = {}
    for line in population:
        demand[line["sku_id"]] = demand.get(line["sku_id"], 0) + line["ordered_qty"]
    for sku_id, units in demand.items():
        if db.skus[sku_id]["on_hand_units"] < units:
            raise ApiError(
                "ERR_INSUFFICIENT_INVENTORY",
                "a SKU of this wave has insufficient uncommitted stock",
            )

    wave["status"] = "PICKING"
    for index, line in enumerate(population):
        sku = db.skus[line["sku_id"]]
        station = selectors.select_station(sku)
        store.insert(db.tasks, {
            "order_line_id": line["id"],
            "sku_id": sku["id"],
            "grid_zone_id": sku["grid_zone_id"],
            "pick_station_id": station["id"],
            "tote_id": None,
            "sequence_index": index + 1,
            "allocated_units": line["ordered_qty"],
            "status": "QUEUED",
            "picked_units": None,
            "actual_weight_grams": None,
        })
    for order in derive.wave_orders(wave):
        if order["fulfillment_status"] == "WAVED":
            order["fulfillment_status"] = "PICKING"
            store.bump(order)
    derive.recompute_all_sku_ledgers()
    money.recompute_surge_for_route(wave["route_id"])
    return resp.obj(wave)


# --------------------------------------------------------------------------
# Consolidation, the loading sequence and dispatch (PRD 3.7)
# --------------------------------------------------------------------------
@bp.route("/delivery-waves/<wave_id>/consolidate", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def consolidate(wave_id):
    wave = must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND")
    v.check_body(v.read_body(), [])
    # gate 11
    if wave["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", "only a PICKING wave can be consolidated")
    # gate 12
    _frozen_gate(wave)
    for task in derive.wave_tasks(wave):
        if task["status"] not in derive.TERMINAL_TASK_STATUSES:
            raise ApiError(
                "ERR_INVALID_STATE", "a retrieval task of this wave is still open"
            )
    # gate 26
    sealed = [t for t in derive.wave_totes(wave) if t["status"] == "SEALED"]
    if not sealed:
        raise ApiError(
            "ERR_NO_TOTES_TO_CONSOLIDATE", "the wave has no SEALED tote to consolidate"
        )

    for tote in sealed:
        tote["status"] = "CONSOLIDATED"
    wave["status"] = "CONSOLIDATED"
    wave["consolidated_by_user_id"] = actor_id()
    for order in derive.wave_orders(wave):
        if order["fulfillment_status"] == "PICKING":
            order["fulfillment_status"] = "CONSOLIDATED"
        if order["fulfillment_status"] != "CANCELLED":
            money.run_waterfall(order)
            store.bump(order)
    derive.recompute_wave_counters(wave)
    return resp.obj(wave)


@bp.route("/delivery-waves/<wave_id>/loading-sequence", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def loading_sequence(wave_id):
    wave = must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND")
    v.check_body(v.read_body(), [])
    # gate 11
    if wave["status"] != "CONSOLIDATED":
        raise ApiError("ERR_INVALID_STATE", "only a CONSOLIDATED wave can be sequenced")
    # gate 12
    _frozen_gate(wave)
    # gate 26
    if wave["dock_bay_id"] is None:
        raise ApiError("ERR_DOCK_NOT_ASSIGNED", "the wave has no dock bay assigned")
    # gate 29
    if any(o["dispatch_blocked"] for o in derive.wave_member_orders(wave)):
        raise ApiError(
            "ERR_ORDER_DISPATCH_BLOCKED",
            "a member order is still awaiting a substitution decision",
        )

    stops = selectors.stop_orders_of(wave)
    wave["load_sequence"] = selectors.loading_sequence(wave, stops)
    wave["transport_cost_cents"] = money.wave_transport_cost(wave, stops)
    wave["status"] = "LOADING"
    for tote in derive.wave_totes(wave):
        if tote["status"] == "CONSOLIDATED":
            tote["status"] = "LOADED"
    for order in derive.wave_orders(wave):
        if order["fulfillment_status"] == "CONSOLIDATED":
            order["fulfillment_status"] = "LOADED"
            store.bump(order)
    derive.recompute_wave_counters(wave)
    return resp.obj(wave)


@bp.route("/delivery-waves/<wave_id>/dispatch", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def dispatch(wave_id):
    wave = must_get(db.waves, wave_id, "ERR_WAVE_NOT_FOUND")
    v.check_body(v.read_body(), [])
    # gate 11
    if wave["status"] != "LOADING":
        raise ApiError("ERR_INVALID_STATE", "only a LOADING wave can be dispatched")
    # gate 12
    _frozen_gate(wave)
    # gate 17
    if actor_id() == wave["consolidated_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the dispatching operator may not be the consolidating operator",
        )
    # gate 29
    if any(o["dispatch_blocked"] for o in derive.wave_member_orders(wave)):
        raise ApiError(
            "ERR_ORDER_DISPATCH_BLOCKED",
            "a member order is still awaiting a substitution decision",
        )

    wave["status"] = "DISPATCHED"
    for order in derive.wave_orders(wave):
        if order["fulfillment_status"] != "LOADED":
            continue
        order["fulfillment_status"] = "DISPATCHED"
        if order["billing_status"] in ("AUTHORIZED", "ADJUSTED"):
            order["billing_status"] = "CAPTURED"
            order["captured_amount_cents"] = order["order_total_cents"]
        store.bump(order)
    money.recompute_surge_for_route(wave["route_id"])
    return resp.obj(wave)


# --------------------------------------------------------------------------
# Totes (PRD 3.5)
# --------------------------------------------------------------------------
@bp.route("/totes", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def open_tote():
    body = v.read_body()
    wave = v.fk(body, "wave_id", db.waves, "ERR_WAVE_NOT_FOUND")
    station = v.fk(body, "pick_station_id", db.stations, "ERR_PICK_STATION_NOT_FOUND")
    data = v.check_body(body, [
        v.f_id("wave_id"),
        v.f_id("pick_station_id"),
        v.f_str("tote_code", 1, 32),
        v.f_enum("temperature_zone", store.TEMPERATURE_ZONES),
    ])
    v.ensure_unique(db.totes, "tote_code", data["tote_code"])
    # gate 12
    _frozen_gate(wave)
    # gate 15
    if data["temperature_zone"] not in station["temperature_zone_capability"]:
        raise ApiError(
            "ERR_STATION_ZONE_UNSUPPORTED",
            "the pick station cannot handle this temperature class",
        )
    # gate 28
    if station["current_tote_count"] >= station["max_concurrent_totes"]:
        raise ApiError(
            "ERR_STATION_TOTE_CAPACITY_EXCEEDED",
            "the pick station is already holding its maximum open totes",
        )
    tote = store.insert(db.totes, {
        "wave_id": wave["id"],
        "pick_station_id": station["id"],
        "tote_code": data["tote_code"],
        "temperature_zone": data["temperature_zone"],
        "status": "OPEN",
        "assigned_line_count": 0,
    })
    derive.recompute_station(station)
    derive.recompute_wave_counters(wave)
    return resp.created(tote)


@bp.route("/totes/<tote_id>", methods=["GET"])
@endpoint(roles=WAVE_READERS)
def read_tote(tote_id):
    return resp.obj(must_get(db.totes, tote_id, "ERR_TOTE_NOT_FOUND"))


@bp.route("/totes", methods=["GET"])
@endpoint(roles=WAVE_READERS)
def list_totes():
    items = resp.filtered(list(db.totes.values()), {
        "wave_id": "wave_id",
        "pick_station_id": "pick_station_id",
        "status": "status",
    })
    return resp.listing(items)


@bp.route("/totes/<tote_id>/seal", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def seal_tote(tote_id):
    tote = must_get(db.totes, tote_id, "ERR_TOTE_NOT_FOUND")
    v.check_body(v.read_body(), [])
    wave = db.waves[tote["wave_id"]]
    # gate 11
    if tote["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "only an OPEN tote can be sealed")
    if wave["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", "the tote's wave is no longer PICKING")
    bound = derive.tote_tasks(tote)
    for task in bound:
        if task["status"] not in derive.TERMINAL_TASK_STATUSES:
            raise ApiError(
                "ERR_INVALID_STATE", "a retrieval task in this tote is still open"
            )
    # gate 12
    _frozen_gate(wave)
    # gate 30
    if not bound:
        raise ApiError("ERR_TOTE_NOT_ASSIGNED", "the tote has no retrieval task assigned")

    tote["status"] = "SEALED"
    derive.recompute_station(db.stations[tote["pick_station_id"]])
    derive.recompute_wave_counters(wave)
    return resp.obj(tote)


@bp.route("/totes/<tote_id>/unseal", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def unseal_tote(tote_id):
    tote = must_get(db.totes, tote_id, "ERR_TOTE_NOT_FOUND")
    v.check_body(v.read_body(), [])
    wave = db.waves[tote["wave_id"]]
    station = db.stations[tote["pick_station_id"]]
    # gate 11
    if tote["status"] != "SEALED":
        raise ApiError("ERR_INVALID_STATE", "only a SEALED tote can be reopened")
    if wave["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", "the tote's wave is no longer PICKING")
    # gate 12
    _frozen_gate(wave)
    # gate 28
    if station["current_tote_count"] >= station["max_concurrent_totes"]:
        raise ApiError(
            "ERR_STATION_TOTE_CAPACITY_EXCEEDED",
            "the pick station is already holding its maximum open totes",
        )

    tote["status"] = "OPEN"
    derive.recompute_station(station)
    derive.recompute_wave_counters(wave)
    return resp.obj(tote)


# --------------------------------------------------------------------------
# Retrieval tasks (PRD 3.5)
# --------------------------------------------------------------------------
@bp.route("/pick-tasks/<task_id>", methods=["GET"])
@endpoint(roles=WAVE_READERS)
def read_task(task_id):
    return resp.obj(must_get(db.tasks, task_id, "ERR_PICK_TASK_NOT_FOUND"))


@bp.route("/pick-tasks", methods=["GET"])
@endpoint(roles=WAVE_READERS)
def list_tasks():
    items = resp.filtered(list(db.tasks.values()), {
        "order_line_id": "order_line_id",
        "sku_id": "sku_id",
        "grid_zone_id": "grid_zone_id",
        "pick_station_id": "pick_station_id",
        "tote_id": "tote_id",
        "status": "status",
    })
    return resp.listing(items)


@bp.route("/pick-tasks/<task_id>/assign-tote", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def assign_tote(task_id):
    task = must_get(db.tasks, task_id, "ERR_PICK_TASK_NOT_FOUND")
    body = v.read_body()
    tote = v.fk(body, "tote_id", db.totes, "ERR_TOTE_NOT_FOUND")
    v.check_body(body, [v.f_id("tote_id")])
    line = derive.task_line(task)
    order = db.orders[line["order_id"]]
    sku = db.skus[task["sku_id"]]
    # gate 11 -- outranks the cold-chain check on purpose (PRD 2.8)
    if task["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE", "only a QUEUED task can be bound to a tote")
    if tote["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "the tote is not OPEN")
    if tote["wave_id"] != order["wave_id"]:
        raise ApiError("ERR_INVALID_STATE", "the tote belongs to a different wave")
    # gate 14
    if tote["temperature_zone"] != sku["temperature_zone"]:
        raise ApiError(
            "ERR_TEMPERATURE_ZONE_MISMATCH",
            "the tote's temperature class differs from the SKU's",
        )
    # gate 30
    if task["tote_id"] is not None:
        raise ApiError("ERR_TOTE_NOT_ASSIGNED", "the task already holds a tote")

    task["tote_id"] = tote["id"]
    derive.recompute_tote(tote)
    return resp.obj(task)


@bp.route("/pick-tasks/<task_id>/start-retrieval", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def start_retrieval(task_id):
    task = must_get(db.tasks, task_id, "ERR_PICK_TASK_NOT_FOUND")
    v.check_body(v.read_body(), [])
    # gate 11
    if task["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE", "only a QUEUED task can start retrieval")
    if task["tote_id"] is None:
        raise ApiError("ERR_TOTE_NOT_ASSIGNED", "the task has no tote bound")
    # gate 13
    zone = db.zones[task["grid_zone_id"]]
    if zone["status"] != "OPERATIONAL":
        raise ApiError("ERR_ZONE_NOT_OPERATIONAL", "the grid zone is not OPERATIONAL")
    wave = derive.line_wave(derive.task_line(task))
    if wave is None or wave["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", "the task's wave is not PICKING")

    task["status"] = "RETRIEVING"
    return resp.obj(task)


@bp.route("/pick-tasks/<task_id>/complete", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def complete_task(task_id):
    task = must_get(db.tasks, task_id, "ERR_PICK_TASK_NOT_FOUND")
    line = derive.task_line(task)
    order = db.orders[line["order_id"]]
    sku = db.skus[task["sku_id"]]
    # gate 8
    data = v.check_body(v.read_body(), [
        v.f_int("picked_units", 0, task["allocated_units"]),
        v.f_int("actual_weight_grams", 0, None, required=False),
    ])
    if sku["is_catchweight"] and data["actual_weight_grams"] is None:
        v.bad("actual_weight_grams is required for a catchweight SKU")
    if not sku["is_catchweight"] and data["actual_weight_grams"] is not None:
        v.bad("actual_weight_grams must be omitted for a non-catchweight SKU")
    # gate 11
    if task["status"] != "RETRIEVING":
        raise ApiError("ERR_INVALID_STATE", "only a RETRIEVING task can be completed")
    # gate 16 -- the tolerance gate runs before any price is written
    if sku["is_catchweight"]:
        nominal_total = line["nominal_weight_grams"] * line["ordered_qty"]
        ratio = money.deviation_ratio(data["actual_weight_grams"], nominal_total)
        if ratio > sku["weight_tolerance_pct"]:
            raise ApiError(
                "ERR_WEIGHT_OUT_OF_TOLERANCE",
                "the measured weight deviates beyond the SKU's tolerance",
            )

    task["picked_units"] = data["picked_units"]
    task["actual_weight_grams"] = data["actual_weight_grams"]
    if data["picked_units"] == task["allocated_units"]:
        task["status"] = "COMPLETED"
        line["line_status"] = "PICKED"
        line["picked_units"] = data["picked_units"]
        line["picked_weight_grams"] = data["actual_weight_grams"]
        line["final_line_price_cents"] = money.final_price_from_pick(
            sku, data["picked_units"], data["actual_weight_grams"]
        )
        sku["physical_units"] = sku["physical_units"] - data["picked_units"]
        derive.recompute_all_sku_ledgers()
        money.run_waterfall(order)
        store.bump(order)
    else:
        task["status"] = "SHORT"
        cascade.short_pick_cascade(task, line, sku)
    if task["tote_id"] is not None:
        derive.recompute_tote(db.totes[task["tote_id"]])
    return resp.obj(task)


@bp.route("/pick-tasks/<task_id>/cancel", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def cancel_task(task_id):
    task = must_get(db.tasks, task_id, "ERR_PICK_TASK_NOT_FOUND")
    v.check_body(v.read_body(), [])
    # gate 11
    if task["status"] not in derive.ACTIVE_TASK_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE", "only a QUEUED or RETRIEVING task can be cancelled"
        )
    wave = derive.line_wave(derive.task_line(task))
    if wave is None or wave["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", "the task's wave is not PICKING")

    task["status"] = "CANCELLED"
    derive.recompute_all_sku_ledgers()
    if task["tote_id"] is not None:
        derive.recompute_tote(db.totes[task["tote_id"]])
    return resp.obj(task)
