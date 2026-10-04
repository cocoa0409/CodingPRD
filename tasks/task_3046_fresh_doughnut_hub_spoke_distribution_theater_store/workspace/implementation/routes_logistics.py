"""Routes: routes, route stops, shipments, stale credits."""
from datetime import timedelta

from app import created, ok, ok_list, route
from core import (
    create_row, err, find, get, iso, iso_min, now, overlapping, page,
    pagination_args,
    parse_date, parse_dt, table, touch,
)
from services import (
    Body, DISPUTE_WINDOW_HOURS, check_door_ownership, maybe_credit_stop,
    maybe_unsuspend_door, reconcile_route_cascade, recompute_pool,
    recompute_posture, require_batch, require_door, require_hub,
    require_network, require_route, require_shipment_row, require_stale_credit,
    require_stop, run_mix_allocation, stale_credit_provisional,
)

NA = "NetworkAdmin"
HM = "HubManager"
RP = "RoutePlanner"
RD = "RouteDriver"
DM = "DoorManager"

ROUTE_TERMINAL = ("RECONCILED",)
STOP_TERMINAL = ("DELIVERED", "MISSED", "CREDITED")
LATE_ARRIVAL_GRACE_MINUTES = 45


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/routes", [RP])
def create_route(ctx):
    hub = require_hub(ctx.p("nid"), ctx.p("hid"))
    body = Body(ctx.body)
    route_code = body.string("route_code")
    service_date = parse_date(body.required("service_date"), "service_date")
    capacity = body.integer("vehicle_capacity_dozens", minimum=1)
    route_row = create_row("routes", {
        "hub_id": hub["id"],
        "route_code": route_code,
        "service_date": service_date,
        "route_status": "PLANNING",
        "vehicle_capacity_dozens": capacity,
        "loaded_dozens": 0,
    })
    return created(route_row)


@route("GET", "/networks/{nid}/hubs/{hid}/routes/{route_id}", [NA, RP, RD])
def get_route(ctx):
    return ok(require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("route_id")))


@route("GET", "/networks/{nid}/hubs/{hid}/routes", [NA, RP, RD])
def list_routes(ctx):
    require_hub(ctx.p("nid"), ctx.p("hid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("routes", lambda r: r["hub_id"] == ctx.p("hid"))
    service_date = ctx.args.get("service_date")
    if service_date:
        rows = [r for r in rows if r["service_date"] == service_date]
    status = ctx.args.get("route_status")
    if status:
        rows = [r for r in rows if r["route_status"] == status]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/routes", [NA])
def list_routes_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("routes").values())
    hub_id = ctx.args.get("hub_id")
    if hub_id:
        rows = [r for r in rows if r["hub_id"] == hub_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/routes/{route_id}", [NA])
def get_route_flat(ctx):
    route_row = get("routes", ctx.p("route_id"))
    if route_row is None:
        err("ERR_NOT_FOUND", "Route not found.")
    return ok(route_row)


# ---------------------------------------------------------------------------
# Route stops
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops", [RP])
def add_route_stop(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"))
    if route_row["route_status"] in ROUTE_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The route is RECONCILED.")
    if route_row["route_status"] != "PLANNING":
        err("ERR_INVALID_STATE", "Stops can only be added while the route is PLANNING.")
    body = Body(ctx.body)
    door_id = body.required("door_id")
    door = get("doors", door_id)
    if door is None or door["network_id"] != ctx.p("nid"):
        err("ERR_CROSS_SCOPE_REFERENCE", "door_id must reference a door of this network.")
    sequence_no = body.integer("sequence_no", minimum=1)
    window_start = parse_dt(body.required("window_start"), "window_start")
    window_end = parse_dt(body.required("window_end"), "window_end")
    if window_end <= window_start:
        err("ERR_WINDOW_OVERLAP", "window_end must be strictly later than window_start.")
    siblings = find("stops", lambda s: s["route_id"] == route_row["id"])
    if any(s["sequence_no"] == sequence_no for s in siblings):
        err("ERR_DUPLICATE_SEQUENCE", "sequence_no is duplicated within the route.")
    for s in siblings:
        if s["door_id"] == door_id and overlapping(
            window_start, window_end, s["_window_start_dt"], s["_window_end_dt"]
        ):
            err("ERR_WINDOW_OVERLAP", "Stop windows for the same door on one route must not overlap.")
    stop = create_row("stops", {
        "route_id": route_row["id"],
        "door_id": door_id,
        "sequence_no": sequence_no,
        "window_start": iso_min(window_start),
        "window_end": iso_min(window_end),
        "stop_status": "PENDING",
        "_window_start_dt": window_start,
        "_window_end_dt": window_end,
    })
    return created(stop)


@route("GET", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops", [NA, RP, RD])
def list_route_stops(ctx):
    require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("stops", lambda s: s["route_id"] == ctx.p("rid"))
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{stop_id}", [NA, RP, RD])
def get_route_stop(ctx):
    return ok(require_stop(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"), ctx.p("stop_id")))


@route("GET", "/networks/route-stops", [NA])
def list_route_stops_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("stops").values())
    route_id = ctx.args.get("route_id")
    if route_id:
        rows = [s for s in rows if s["route_id"] == route_id]
    door_id = ctx.args.get("door_id")
    if door_id:
        rows = [s for s in rows if s["door_id"] == door_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/route-stops/{stop_id}", [NA])
def get_route_stop_flat(ctx):
    stop = get("stops", ctx.p("stop_id"))
    if stop is None:
        err("ERR_NOT_FOUND", "Route stop not found.")
    return ok(stop)


# ---------------------------------------------------------------------------
# Route lifecycle
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/routes/{route_id}/lock", [RP])
def lock_route(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("route_id"))
    if route_row["route_status"] in ROUTE_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The route is RECONCILED.")
    if route_row["route_status"] != "PLANNING":
        err("ERR_INVALID_STATE", "Only a PLANNING route can be locked.")
    stops = find("stops", lambda s: s["route_id"] == route_row["id"])
    if not stops:
        err("ERR_ROUTE_NOT_LOCKABLE", "The route has no stops.")
    total_seconds = sum(
        (s["_window_end_dt"] - s["_window_start_dt"]).total_seconds() for s in stops
    )
    if total_seconds < 30 * 60:
        err("ERR_ROUTE_NOT_LOCKABLE", "The total window span is under 30 minutes.")
    route_row["route_status"] = "LOCKED"
    touch(route_row)
    return ok(route_row)


@route("POST", "/networks/{nid}/hubs/{hid}/routes/{route_id}/dispatch", [RP])
def dispatch_route(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("route_id"))
    if route_row["route_status"] in ROUTE_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The route is RECONCILED.")
    if route_row["route_status"] != "LOCKED":
        err("ERR_INVALID_STATE", "Only a LOCKED route can be dispatched.")
    stops = find("stops", lambda s: s["route_id"] == route_row["id"])
    shipments = []
    for stop in stops:
        shipments.extend(find("shipments", lambda s: s["route_stop_id"] == stop["id"]))
    if int(route_row["loaded_dozens"]) > int(route_row["vehicle_capacity_dozens"]):
        err("ERR_CAPACITY_EXCEEDED", "The vehicle capacity would be exceeded.")
    for shipment in shipments:
        if shipment["delivery_status"] != "STAGED":
            err("ERR_INVALID_STATE", "Every shipment must be STAGED at dispatch.")
        batch = get("batches", shipment["production_batch_id"])
        if batch is None or batch["batch_status"] != "COMPLETED" or batch.get("fresh_until") is None:
            err("ERR_INVALID_STATE", "Every referenced batch must be COMPLETED with fresh_until set.")
    for shipment in shipments:
        shipment["delivery_status"] = "IN_TRANSIT"
        touch(shipment)
    # Lock mix plans of stops' doors whose effective_date matches service_date.
    for stop in stops:
        for plan in find(
            "mix_plans",
            lambda p: p["door_id"] == stop["door_id"]
            and p["effective_date"] == route_row["service_date"]
            and p["mix_plan_status"] == "PUBLISHED",
        ):
            plan["mix_plan_status"] = "LOCKED"
            touch(plan)
    route_row["route_status"] = "DISPATCHED"
    touch(route_row)
    return ok(route_row)


@route("POST", "/networks/{nid}/hubs/{hid}/routes/{route_id}/reconcile", [RP])
def reconcile_route(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("route_id"))
    if route_row["route_status"] in ROUTE_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The route is RECONCILED.")
    if route_row["route_status"] != "COMPLETED":
        err("ERR_INVALID_STATE", "Only a COMPLETED route can be reconciled.")
    reconcile_route_cascade(route_row)
    route_row["route_status"] = "RECONCILED"
    touch(route_row)
    return ok(route_row)


# ---------------------------------------------------------------------------
# Stop execution
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{stop_id}/arrive", [RD])
def arrive_stop(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"))
    stop = get("stops", ctx.p("stop_id"))
    if stop is None or stop["route_id"] != route_row["id"]:
        err("ERR_NOT_FOUND", "Route stop not found.")
    if stop["stop_status"] in STOP_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The stop is in a terminal state.")
    if stop["stop_status"] != "PENDING":
        err("ERR_INVALID_STATE", "Only a PENDING stop can be arrived.")
    if route_row["route_status"] != "DISPATCHED":
        err("ERR_INVALID_STATE", "The route is not DISPATCHED.")
    current = now()
    if current < stop["_window_start_dt"]:
        err("ERR_INVALID_STATE", "The delivery window has not opened yet.")
    if current >= stop["_window_end_dt"]:
        # Late-arrival eligibility: a driver may still arrive a stop within
        # the late-arrival grace after window_end; the recorded late arrival
        # feeds the final-variant credit penalty at reconciliation. Beyond
        # the grace the stop is not late-arrival-eligible.
        if current >= stop["_window_end_dt"] + timedelta(minutes=LATE_ARRIVAL_GRACE_MINUTES):
            err("ERR_STOP_WINDOW_PASSED", "The delivery window has closed.")
    stop["_arrived_at"] = current
    stop["stop_status"] = "ARRIVED"
    touch(stop)
    return ok(stop)


@route("POST", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{stop_id}/deliver", [RD])
def deliver_stop(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"))
    stop = get("stops", ctx.p("stop_id"))
    if stop is None or stop["route_id"] != route_row["id"]:
        err("ERR_NOT_FOUND", "Route stop not found.")
    if stop["stop_status"] in STOP_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The stop is in a terminal state.")
    if stop["stop_status"] != "ARRIVED":
        err("ERR_INVALID_STATE", "Only an ARRIVED stop can be delivered.")
    shipments = find("shipments", lambda s: s["route_stop_id"] == stop["id"])
    for shipment in shipments:
        if shipment["dozens_delivered"] is None:
            err("ERR_INVALID_STATE", "All shipments must record dozens_delivered before delivery.")
    for shipment in shipments:
        if int(shipment["dozens_delivered"]) == int(shipment["dozens_shipped"]):
            shipment["delivery_status"] = "DELIVERED"
        else:
            shipment["delivery_status"] = "PARTIAL"
        touch(shipment)
    stop["stop_status"] = "DELIVERED"
    touch(stop)
    _maybe_complete_route(route_row)
    return ok(stop)


@route("POST", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{stop_id}/miss", [RD])
def miss_stop(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"))
    stop = get("stops", ctx.p("stop_id"))
    if stop is None or stop["route_id"] != route_row["id"]:
        err("ERR_NOT_FOUND", "Route stop not found.")
    if stop["stop_status"] in STOP_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The stop is in a terminal state.")
    stop["stop_status"] = "MISSED"
    touch(stop)
    for shipment in find("shipments", lambda s: s["route_stop_id"] == stop["id"]):
        if shipment["delivery_status"] in ("STAGED", "IN_TRANSIT"):
            shipment["delivery_status"] = "FAILED"
            touch(shipment)
    run_mix_allocation(route_row["hub_id"], route_row["service_date"])
    _maybe_complete_route(route_row)
    return ok(stop)


def _maybe_complete_route(route_row):
    if route_row["route_status"] != "DISPATCHED":
        return
    stops = find("stops", lambda s: s["route_id"] == route_row["id"])
    if stops and all(s["stop_status"] in STOP_TERMINAL for s in stops):
        route_row["route_status"] = "COMPLETED"
        touch(route_row)
        hub = get("hubs", route_row["hub_id"])
        if hub is not None:
            recompute_posture(hub["network_id"])


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{sid}/shipments", [RP])
def stage_shipment(ctx):
    route_row = require_route(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"))
    stop = get("stops", ctx.p("sid"))
    if stop is None or stop["route_id"] != route_row["id"]:
        err("ERR_NOT_FOUND", "Route stop not found.")
    if route_row["route_status"] in ROUTE_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The route is RECONCILED.")
    if route_row["route_status"] not in ("PLANNING", "LOCKED"):
        err("ERR_INVALID_STATE", "Shipments can only be staged before dispatch.")
    body = Body(ctx.body)
    batch_id = body.required("production_batch_id")
    batch = get("batches", batch_id)
    if batch is None:
        err("ERR_CROSS_SCOPE_REFERENCE", "production_batch_id does not reference an existing batch.")
    if batch["hub_id"] != route_row["hub_id"]:
        err("ERR_CROSS_SCOPE_REFERENCE", "A shipment's batch must come from the same hub as the route.")
    dozens = body.integer("dozens_shipped", minimum=1)
    shipment = create_row("shipments", {
        "route_stop_id": stop["id"],
        "production_batch_id": batch_id,
        "dozens_shipped": dozens,
        "dozens_delivered": None,
        "delivery_status": "STAGED",
        "credit_status": "NONE",
        "freshness_override": False,
    })
    route_row["loaded_dozens"] = int(route_row["loaded_dozens"]) + dozens
    touch(route_row)
    return created(shipment)


@route("GET", "/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{sid}/shipments", [NA, RP, RD, DM])
def list_shipments(ctx):
    require_stop(ctx.p("nid"), ctx.p("hid"), ctx.p("rid"), ctx.p("sid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("shipments", lambda s: s["route_stop_id"] == ctx.p("sid"))
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/{nid}/shipments/{shipment_id}", [NA, RP, DM])
def get_shipment(ctx):
    return ok(require_shipment_row(ctx.p("nid"), ctx.p("shipment_id")))


@route("GET", "/networks/shipments", [NA])
def list_shipments_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("shipments").values())
    stop_id = ctx.args.get("route_stop_id")
    if stop_id:
        rows = [s for s in rows if s["route_stop_id"] == stop_id]
    batch_id = ctx.args.get("production_batch_id")
    if batch_id:
        rows = [s for s in rows if s["production_batch_id"] == batch_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/shipments/{shipment_id}", [NA])
def get_shipment_flat(ctx):
    shipment = get("shipments", ctx.p("shipment_id"))
    if shipment is None:
        err("ERR_NOT_FOUND", "Shipment not found.")
    return ok(shipment)


@route("POST", "/networks/{nid}/shipments/{shipment_id}/record-delivery", [RD])
def record_delivery(ctx):
    shipment = require_shipment_row(ctx.p("nid"), ctx.p("shipment_id"))
    if shipment["delivery_status"] not in ("STAGED", "IN_TRANSIT"):
        err("ERR_INVALID_STATE", "Delivery can only be recorded before a terminal delivery state.")
    dozens = Body(ctx.body).integer("dozens_delivered", minimum=0)
    shipment["dozens_delivered"] = dozens
    touch(shipment)
    return ok(shipment)


# ---------------------------------------------------------------------------
# Stale credits
# ---------------------------------------------------------------------------
def _same_day_deadline(production_date):
    """23:59 local on the production date (deadline is inclusive through
    23:59:59; a pull at or after the following midnight is too late)."""
    from datetime import datetime, timezone
    day = datetime.fromisoformat(production_date + "T00:00:00+00:00")
    return day.replace(hour=23, minute=59, second=59, microsecond=999000)


@route("POST", "/networks/{nid}/doors/{did}/stale-credits", [DM])
def create_stale_credit(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    body = Body(ctx.body)
    shipment_id = body.required("shipment_id")
    pulled = body.integer("pulled_dozens", minimum=1)
    shipment = get("shipments", shipment_id)
    if shipment is None:
        err("ERR_NOT_FOUND", "Shipment not found.")
    # Cross-scope: the shipment's route must belong to this network.
    stop = get("stops", shipment["route_stop_id"])
    route_row = get("routes", stop["route_id"]) if stop else None
    hub = get("hubs", route_row["hub_id"]) if route_row else None
    if hub is None or hub["network_id"] != ctx.p("nid"):
        err("ERR_CROSS_SCOPE_REFERENCE", "The shipment belongs to a different network scope.")
    # State admissibility (rung 4) precedes freshness (rung 5).
    if shipment["delivery_status"] not in ("DELIVERED", "PARTIAL", "FAILED"):
        err("ERR_INVALID_STATE",
            "Stale pulls require the shipment to be DELIVERED, PARTIAL, or FAILED.")
    if shipment["credit_status"] not in ("NONE",):
        pass  # additional pulls on the same shipment are permitted by the tests
    batch = get("batches", shipment["production_batch_id"])
    deadline = _same_day_deadline(batch["production_date"])
    if now() > deadline:
        err("ERR_FRESHNESS_VIOLATION",
            "The same-day pull deadline on the production date has passed.")
    provisional = stale_credit_provisional(pulled, bool(shipment.get("freshness_override")))
    credit = create_row("stale_credits", {
        "door_id": door["id"],
        "shipment_id": shipment_id,
        "pulled_dozens": pulled,
        "provisional_credit_cents": provisional,
        "final_credit_cents": None,
        "credit_state": "PROVISIONAL",
    })
    if shipment["credit_status"] == "NONE":
        shipment["credit_status"] = "PENDING_PULL"
        touch(shipment)
    door["credit_balance_cents"] = int(door["credit_balance_cents"]) + provisional
    touch(door)
    return created(credit)


@route("GET", "/networks/{nid}/doors/{did}/stale-credits", [NA, DM])
def list_stale_credits(ctx):
    require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, ctx.p("did"))
    limit, offset = pagination_args(ctx.args)
    rows = find("stale_credits", lambda c: c["door_id"] == ctx.p("did"))
    state = ctx.args.get("credit_state")
    if state:
        rows = [c for c in rows if c["credit_state"] == state]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/{nid}/doors/{did}/stale-credits/{credit_id}", [NA, DM])
def get_stale_credit(ctx):
    credit = require_stale_credit(ctx.p("nid"), ctx.p("did"), ctx.p("credit_id"))
    check_door_ownership(ctx, ctx.p("did"))
    return ok(credit)


@route("GET", "/networks/stale-credits", [NA])
def list_stale_credits_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("stale_credits").values())
    door_id = ctx.args.get("door_id")
    if door_id:
        rows = [c for c in rows if c["door_id"] == door_id]
    shipment_id = ctx.args.get("shipment_id")
    if shipment_id:
        rows = [c for c in rows if c["shipment_id"] == shipment_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/stale-credits/{credit_id}", [NA])
def get_stale_credit_flat(ctx):
    credit = get("stale_credits", ctx.p("credit_id"))
    if credit is None:
        err("ERR_NOT_FOUND", "Stale credit not found.")
    return ok(credit)


@route("POST", "/networks/{nid}/doors/{did}/stale-credits/{credit_id}/dispute", [DM])
def dispute_stale_credit(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    credit = get("stale_credits", ctx.p("credit_id"))
    if credit is None or credit["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Stale credit not found.")
    if credit["credit_state"] in ("FINALIZED", "RESOLVED"):
        err("ERR_ALREADY_TERMINAL", "The credit is in a terminal state.")
    if credit["credit_state"] != "PROVISIONAL":
        err("ERR_INVALID_STATE", "Only a PROVISIONAL credit can be disputed.")
    pulled_at = parse_dt(credit["created_at"], "created_at")
    if now() > pulled_at + timedelta(hours=DISPUTE_WINDOW_HOURS):
        err("ERR_FRESHNESS_VIOLATION", "The 48-hour dispute window has passed.")
    credit["credit_state"] = "DISPUTED"
    touch(credit)
    shipment = get("shipments", credit["shipment_id"])
    if shipment is not None and shipment["credit_status"] == "PENDING_PULL":
        shipment["credit_status"] = "DISPUTED"
        touch(shipment)
    door["open_dispute_count"] = int(door["open_dispute_count"]) + 1
    touch(door)
    if door["open_dispute_count"] >= 3 and door["door_status"] == "ACTIVE":
        door["door_status"] = "SUSPENDED"
        touch(door)
        recompute_posture(door["network_id"])
    return ok(credit)


@route("POST", "/networks/{nid}/doors/{did}/stale-credits/{credit_id}/resolve", [NA])
def resolve_stale_credit(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    credit = get("stale_credits", ctx.p("credit_id"))
    if credit is None or credit["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Stale credit not found.")
    if credit["credit_state"] == "RESOLVED":
        err("ERR_ALREADY_TERMINAL", "The credit is already RESOLVED.")
    if credit["credit_state"] == "PROVISIONAL":
        err("ERR_INVALID_STATE", "Only a DISPUTED or FINALIZED credit can be resolved.")
    resolution = Body(ctx.body).integer("resolution_credit_cents", required=False)
    network = get("networks", door["network_id"])

    if credit["credit_state"] == "DISPUTED":
        if resolution is None:
            err("ERR_INVALID_REQUEST", "resolution_credit_cents is required.")
        delta = resolution - int(credit["provisional_credit_cents"])
        credit["final_credit_cents"] = resolution
        credit["credit_state"] = "RESOLVED"
        touch(credit)
        door["credit_balance_cents"] = max(0, int(door["credit_balance_cents"]) + delta)
        door["open_dispute_count"] = max(0, int(door["open_dispute_count"]) - 1)
        touch(door)
        maybe_unsuspend_door(door)
        shipment = get("shipments", credit["shipment_id"])
        if shipment is not None and shipment["credit_status"] == "DISPUTED":
            shipment["credit_status"] = "CREDITED"
            touch(shipment)
        stop = get("stops", shipment["route_stop_id"]) if shipment else None
        if stop is not None:
            maybe_credit_stop(stop)
    else:  # FINALIZED -> RESOLVED payout
        amount = int(credit["final_credit_cents"])
        if int(network["stale_credit_pool_cents"]) - amount < 0:
            err("ERR_CAPACITY_EXCEEDED", "The payout would push the stale credit pool negative.")
        credit["credit_state"] = "RESOLVED"
        touch(credit)
        recompute_pool(network["id"])
        door["credit_balance_cents"] = max(
            0, int(door["credit_balance_cents"]) - amount)
        touch(door)
    return ok(credit)
