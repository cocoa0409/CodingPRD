"""Routes: fundraiser orders and hot-light windows (door-scoped resources)."""
import uuid
from datetime import timedelta

from app import created, ok, ok_list, route
from core import (
    create_row, err, find, get, iso, iso_min, now, overlapping, page,
    pagination_args,
    parse_dt, table, today_str, touch,
)
from services import (
    Body, LEAD_TIME_HOURS, PICKUP_GRACE_HOURS, check_door_ownership,
    demand_response_cap, door_has_fresh_batch_today, fundraiser_quote,
    require_door, require_fundraiser, require_window, theater_hub_for_door,
)

NA = "NetworkAdmin"
DM = "DoorManager"

FUNDRAISER_TERMINAL = ("FULFILLED", "CANCELLED", "EXPIRED")
WINDOW_TERMINAL = ("COMPLETED", "CANCELLED")


def _door_hub_id(door):
    """Hub that supplies this door for production purposes; THEATER doors are
    self-supplied and resolve to the network's hub."""
    if door.get("hub_id"):
        return door["hub_id"]
    return theater_hub_for_door(door)


# ---------------------------------------------------------------------------
# Fundraiser orders (PRD §3.7)
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders", [DM])
def create_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    body = Body(ctx.body)
    organization_name = body.string("organization_name")
    requested = body.integer("requested_dozens", minimum=1)
    pickup_dt = parse_dt(body.required("pickup_at"), "pickup_at")
    if pickup_dt < now() + timedelta(hours=LEAD_TIME_HOURS):
        err("ERR_FRESHNESS_VIOLATION",
            "pickup_at is inside the lead-time horizon.")
    order = create_row("fundraisers", {
        "door_id": door["id"],
        "organization_name": organization_name,
        "requested_dozens": requested,
        "pickup_at": iso_min(pickup_dt),
        "fundraiser_status": "SUBMITTED",
        "quoted_total_cents": None,
        "pickup_code": None,
        "_pickup_dt": pickup_dt,
    })
    return created(order)


@route("GET", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}", [NA, DM])
def get_fundraiser_order(ctx):
    order = require_fundraiser(ctx.p("nid"), ctx.p("did"), ctx.p("order_id"))
    check_door_ownership(ctx, ctx.p("did"))
    return ok(order)


@route("GET", "/networks/{nid}/doors/{did}/fundraiser-orders", [NA, DM])
def list_fundraiser_orders(ctx):
    require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, ctx.p("did"))
    limit, offset = pagination_args(ctx.args)
    rows = find("fundraisers", lambda o: o["door_id"] == ctx.p("did"))
    status = ctx.args.get("fundraiser_status")
    if status:
        rows = [o for o in rows if o["fundraiser_status"] == status]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/fundraiser-orders", [NA])
def list_fundraiser_orders_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("fundraisers").values())
    door_id = ctx.args.get("door_id")
    if door_id:
        rows = [o for o in rows if o["door_id"] == door_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/fundraiser-orders/{order_id}", [NA])
def get_fundraiser_order_flat(ctx):
    order = get("fundraisers", ctx.p("order_id"))
    if order is None:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    return ok(order)


@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}/approve", [DM])
def approve_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    order = get("fundraisers", ctx.p("order_id"))
    if order is None or order["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    if order["fundraiser_status"] in FUNDRAISER_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The fundraiser order is in a terminal state.")
    if order["fundraiser_status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Only a SUBMITTED order can be approved.")
    if door["door_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "The door is not ACTIVE.")
    if order["_pickup_dt"] < now() + timedelta(hours=LEAD_TIME_HOURS):
        err("ERR_FRESHNESS_VIOLATION", "pickup_at is inside the lead-time horizon.")
    hub_id = _door_hub_id(door)
    if hub_id is not None:
        hub = get("hubs", hub_id)
        if hub is not None and int(order["requested_dozens"]) > int(hub["daily_capacity_dozens"]):
            err("ERR_CAPACITY_EXCEEDED",
                "requested_dozens exceeds the hub's daily capacity on the pickup date.")
    order["quoted_total_cents"] = fundraiser_quote(
        int(order["requested_dozens"]), order["organization_name"])
    order["fundraiser_status"] = "APPROVED"
    touch(order)
    return ok(order)


@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}/return-for-changes", [DM])
def return_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    order = get("fundraisers", ctx.p("order_id"))
    if order is None or order["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    if order["fundraiser_status"] in FUNDRAISER_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The fundraiser order is in a terminal state.")
    if order["fundraiser_status"] != "APPROVED":
        err("ERR_INVALID_STATE", "Only an APPROVED order can be returned for changes.")
    order["fundraiser_status"] = "SUBMITTED"
    order["quoted_total_cents"] = None
    touch(order)
    return ok(order)


@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}/schedule", [DM])
def schedule_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    order = get("fundraisers", ctx.p("order_id"))
    if order is None or order["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    if order["fundraiser_status"] in FUNDRAISER_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The fundraiser order is in a terminal state.")
    if order["fundraiser_status"] != "APPROVED":
        err("ERR_INVALID_STATE", "Only an APPROVED order can be scheduled.")
    hub_id = _door_hub_id(door)
    pickup_date = order["_pickup_dt"].date().isoformat()
    covering = None
    if hub_id is not None:
        for batch in find(
            "batches",
            lambda b: b["hub_id"] == hub_id
            and b["production_date"] == pickup_date
            and b["batch_status"] in ("COMMITTED", "COMPLETED"),
        ):
            coverage = (
                int(batch["produced_dozens"]) if batch["batch_status"] == "COMPLETED"
                else int(batch["planned_dozens"])
            )
            if coverage >= int(order["requested_dozens"]):
                covering = batch
                break
    if covering is None:
        err("ERR_INVALID_STATE",
            "No COMMITTED or COMPLETED batch covers the requested dozens on the pickup date.")
    order["fundraiser_status"] = "SCHEDULED"
    order["_covering_batch_id"] = covering["id"]
    touch(order)
    return ok(order)


@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}/ready", [DM])
def ready_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    order = get("fundraisers", ctx.p("order_id"))
    if order is None or order["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    if order["fundraiser_status"] in FUNDRAISER_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The fundraiser order is in a terminal state.")
    if order["fundraiser_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Only a SCHEDULED order can be marked ready.")
    covering = get("batches", order.get("_covering_batch_id"))
    if covering is None or covering["batch_status"] != "COMPLETED" or (
        int(covering.get("produced_dozens") or 0) < int(order["requested_dozens"])
    ):
        err("ERR_INVALID_STATE",
            "The covering batch must be COMPLETED with produced_dozens >= requested_dozens.")
    order["fundraiser_status"] = "READY"
    order["pickup_code"] = uuid.uuid4().hex[:8].upper()
    touch(order)
    return ok(order)


@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}/fulfill", [DM])
def fulfill_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    order = get("fundraisers", ctx.p("order_id"))
    if order is None or order["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    if order["fundraiser_status"] in FUNDRAISER_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The fundraiser order is in a terminal state.")
    if order["fundraiser_status"] != "READY":
        err("ERR_INVALID_STATE", "Only a READY order can be fulfilled.")
    body = Body(ctx.body)
    code = body.required("pickup_code")
    if code != order["pickup_code"]:
        err("ERR_PICKUP_CODE_MISMATCH", "The pickup code does not match.")
    if now() > order["_pickup_dt"] + timedelta(hours=PICKUP_GRACE_HOURS):
        err("ERR_FRESHNESS_VIOLATION", "The pickup grace window has elapsed.")
    order["fundraiser_status"] = "FULFILLED"
    touch(order)
    return ok(order)


@route("POST", "/networks/{nid}/doors/{did}/fundraiser-orders/{order_id}/cancel", [DM])
def cancel_fundraiser_order(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    order = get("fundraisers", ctx.p("order_id"))
    if order is None or order["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Fundraiser order not found.")
    if order["fundraiser_status"] in FUNDRAISER_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The fundraiser order is in a terminal state.")
    if order["fundraiser_status"] not in ("SUBMITTED", "APPROVED"):
        err("ERR_INVALID_STATE", "Only SUBMITTED or APPROVED orders can be cancelled.")
    order["fundraiser_status"] = "CANCELLED"
    touch(order)
    return ok(order)


# ---------------------------------------------------------------------------
# Hot-light windows (PRD §3.8)
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/doors/{did}/hot-light-windows", [DM])
def create_hot_light_window(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    body = Body(ctx.body)
    if door["door_kind"] != "THEATER":
        err("ERR_TERRITORY_VIOLATION", "Only THEATER doors may have hot-light windows.")
    lit_start = parse_dt(body.required("lit_start"), "lit_start")
    lit_end = parse_dt(body.required("lit_end"), "lit_end")
    extend = body.integer("demand_response_extend_minutes", required=False,
                          minimum=0, default=0)
    if extend > 90:
        err("ERR_INVALID_REQUEST", "demand_response_extend_minutes must lie between 0 and 90.")
    if lit_end <= lit_start:
        err("ERR_WINDOW_OVERLAP", "lit_end must be strictly later than lit_start.")
    for w in find(
        "hot_light_windows",
        lambda w: w["door_id"] == door["id"] and w["window_status"] not in WINDOW_TERMINAL,
    ):
        # Overlap is judged against the window's scheduled span at creation;
        # a later demand-response extension does not retroactively make an
        # already-scheduled window overlapping (PRD §3.8).
        orig_end = w.get("_orig_lit_end_dt", w["_lit_end_dt"])
        if overlapping(lit_start, lit_end, w["_lit_start_dt"], orig_end):
            err("ERR_WINDOW_OVERLAP", "Hot-light windows for the same door must not overlap.")
    window = create_row("hot_light_windows", {
        "door_id": door["id"],
        "lit_start": iso_min(lit_start),
        "lit_end": iso_min(lit_end),
        "window_status": "SCHEDULED",
        "demand_response_extend_minutes": extend,
        "_lit_start_dt": lit_start,
        "_lit_end_dt": lit_end,
        "_orig_lit_end_dt": lit_end,
    })
    return created(window)


@route("GET", "/networks/{nid}/doors/{did}/hot-light-windows", [NA, DM])
def list_hot_light_windows(ctx):
    require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, ctx.p("did"))
    limit, offset = pagination_args(ctx.args)
    rows = find("hot_light_windows", lambda w: w["door_id"] == ctx.p("did"))
    status = ctx.args.get("window_status")
    if status:
        rows = [w for w in rows if w["window_status"] == status]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/{nid}/doors/{did}/hot-light-windows/{window_id}", [NA, DM])
def get_hot_light_window(ctx):
    window = require_window(ctx.p("nid"), ctx.p("did"), ctx.p("window_id"))
    check_door_ownership(ctx, ctx.p("did"))
    return ok(window)


@route("GET", "/networks/hot-light-windows", [NA])
def list_hot_light_windows_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("hot_light_windows").values())
    door_id = ctx.args.get("door_id")
    if door_id:
        rows = [w for w in rows if w["door_id"] == door_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/hot-light-windows/{window_id}", [NA])
def get_hot_light_window_flat(ctx):
    window = get("hot_light_windows", ctx.p("window_id"))
    if window is None:
        err("ERR_NOT_FOUND", "Hot-light window not found.")
    return ok(window)


@route("POST", "/networks/{nid}/doors/{did}/hot-light-windows/{window_id}/ignite", [DM])
def ignite_hot_light_window(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    window = get("hot_light_windows", ctx.p("window_id"))
    if window is None or window["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Hot-light window not found.")
    if window["window_status"] in WINDOW_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The window is in a terminal state.")
    if window["window_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Only a SCHEDULED window can be ignited.")
    other_lit = any(
        w["window_status"] in ("LIT", "EXTENDED") and w["id"] != window["id"]
        for w in find("hot_light_windows", lambda w: w["door_id"] == door["id"])
    )
    if other_lit:
        err("ERR_INVALID_STATE",
            "Another window for this door is currently LIT or EXTENDED.")
    if not door_has_fresh_batch_today(door):
        err("ERR_FRESHNESS_VIOLATION",
            "No fresh COMPLETED batch exists at the door's hub today.")
    window["window_status"] = "LIT"
    touch(window)
    return ok(window)


@route("POST", "/networks/{nid}/doors/{did}/hot-light-windows/{window_id}/extend", [DM])
def extend_hot_light_window(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    window = get("hot_light_windows", ctx.p("window_id"))
    if window is None or window["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Hot-light window not found.")
    if window["window_status"] in WINDOW_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The window is in a terminal state.")
    if window["window_status"] != "LIT":
        err("ERR_INVALID_STATE", "Only a LIT window can be extended.")
    body = Body(ctx.body)
    requested = body.integer("demand_response_extend_minutes", minimum=1)
    if requested > 90:
        err("ERR_INVALID_REQUEST", "demand_response_extend_minutes must lie between 1 and 90.")
    if not door_has_fresh_batch_today(door):
        err("ERR_FRESHNESS_VIOLATION",
            "No fresh COMPLETED batch exists at the door's hub today.")
    cap = demand_response_cap(door)
    if requested > cap:
        err("ERR_DEMAND_CAP_EXCEEDED",
            "The requested extension exceeds the demand-response cap.")
    granted = min(requested, cap)
    new_end = window["_lit_end_dt"] + timedelta(minutes=granted)
    window["_lit_end_dt"] = new_end
    window["lit_end"] = iso_min(new_end)
    window["demand_response_extend_minutes"] = int(
        window.get("demand_response_extend_minutes") or 0) + granted
    window["window_status"] = "EXTENDED"
    touch(window)
    return ok(window)


@route("POST", "/networks/{nid}/doors/{did}/hot-light-windows/{window_id}/cancel", [DM])
def cancel_hot_light_window(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    window = get("hot_light_windows", ctx.p("window_id"))
    if window is None or window["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Hot-light window not found.")
    if window["window_status"] in WINDOW_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The window is in a terminal state.")
    if window["window_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Only a SCHEDULED window can be cancelled.")
    window["window_status"] = "CANCELLED"
    touch(window)
    return ok(window)
