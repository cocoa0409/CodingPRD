"""Routes: logical clock, networks, hubs, doors, varieties, ops-run checkpoint."""
from datetime import timedelta

from app import Ctx, created, ok, ok_list, route
from core import (
    CLOCK, create_row, err, find, get, iso, iso_min, now, page, pagination_args,
    parse_date, parse_dt, table, today_str, touch,
)
from services import (
    Body, LEAD_TIME_HOURS, PICKUP_GRACE_HOURS, effective_dozens,
    enter_maintenance, maybe_suspend_door_for_hub_lines, recompute_pool,
    recompute_posture, require_door, require_hub, require_network,
    require_variety, run_mix_allocation,
)

NA = "NetworkAdmin"
HM = "HubManager"
RP = "RoutePlanner"
RD = "RouteDriver"
DM = "DoorManager"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
@route("POST", "/networks/_clock/set_current_utc", [NA])
def set_clock(ctx: Ctx):
    body = Body(ctx.body)
    to_iso = body.required("to_iso8601")
    CLOCK.set(to_iso)
    from services import apply_time_transitions
    apply_time_transitions()
    return ok({"current_utc": iso(now())})


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------
@route("POST", "/networks", [NA])
def create_network(ctx: Ctx):
    body = Body(ctx.body)
    network_code = body.string("network_code")
    display_name = body.string("display_name")
    network = create_row("networks", {
        "network_code": network_code,
        "display_name": display_name,
        "network_posture": "OPEN",
        "ops_run_index": 0,
        "stale_credit_pool_cents": 0,
    })
    return created(network)


@route("GET", "/networks/{network_id}", [NA, HM, RP, DM, RD])
def get_network(ctx: Ctx):
    network = require_network(ctx.p("network_id"))
    return ok(network)


@route("GET", "/networks", [NA])
def list_networks(ctx: Ctx):
    limit, offset = pagination_args(ctx.args)
    rows, meta = page(list(table("networks").values()), limit, offset)
    return ok_list(rows, meta)


@route("POST", "/networks/{network_id}/ops-runs", [NA])
def run_ops_run(ctx: Ctx):
    """Ops-run checkpoint (PRD §3.9): full posture recompute, expire stale
    batches and orders, force over-service lines into maintenance, advance the
    index, bump the network version."""
    network = require_network(ctx.p("network_id"))
    current = now()
    today = today_str()
    expired_batches = 0
    expired_orders = 0

    # Auto-cancel SCHEDULED batches whose production_date fell in the past.
    network_hubs = find("hubs", lambda h: h["network_id"] == network["id"])
    hub_ids = {h["id"] for h in network_hubs}
    for batch in find("batches", lambda b: b["hub_id"] in hub_ids):
        if batch["batch_status"] == "SCHEDULED" and batch["production_date"] < today:
            batch["batch_status"] = "CANCELLED"
            touch(batch)
            expired_batches += 1

    # Auto-expire READY fundraiser orders past the pickup grace.
    network_doors = find("doors", lambda d: d["network_id"] == network["id"])
    door_ids = {d["id"] for d in network_doors}
    for order in find("fundraisers", lambda o: o["door_id"] in door_ids):
        if order["fundraiser_status"] == "READY" and current >= (
            order["_pickup_dt"] + timedelta(hours=PICKUP_GRACE_HOURS)
        ):
            order["fundraiser_status"] = "EXPIRED"
            touch(order)
            expired_orders += 1

    # Force over-service lines into MAINTENANCE with the standard cascade.
    for line in find("lines", lambda l: l["hub_id"] in hub_ids):
        if line["line_status"] in ("OPERATIONAL", "DEGRADED") and (
            float(line["hours_since_service"]) >= line["service_interval_hours"]
        ):
            enter_maintenance(line)

    # Full posture recompute (ops_run_projection variant).
    recompute_posture(network["id"])
    recompute_pool(network["id"])

    network["ops_run_index"] = int(network["ops_run_index"]) + 1
    touch(network)
    return created({
        "ops_run_index": network["ops_run_index"],
        "expired_batch_count": expired_batches,
        "expired_order_count": expired_orders,
        "network_posture": network["network_posture"],
    })


# ---------------------------------------------------------------------------
# Hubs
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs", [NA])
def create_hub(ctx: Ctx):
    require_network(ctx.p("nid"))
    body = Body(ctx.body)
    hub_code = body.string("hub_code")
    capacity = body.integer("daily_capacity_dozens", minimum=1)
    region = body.string("territory_region")
    hub = create_row("hubs", {
        "network_id": ctx.p("nid"),
        "hub_code": hub_code,
        "daily_capacity_dozens": capacity,
        "committed_dozens_today": 0,
        "territory_region": region,
    })
    return created(hub)


@route("GET", "/networks/{nid}/hubs/{hub_id}", [NA, HM, RP])
def get_hub(ctx: Ctx):
    return ok(require_hub(ctx.p("nid"), ctx.p("hub_id")))


@route("GET", "/networks/{nid}/hubs", [NA, HM, RP])
def list_hubs(ctx: Ctx):
    require_network(ctx.p("nid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("hubs", lambda h: h["network_id"] == ctx.p("nid"))
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/hubs", [NA])
def list_hubs_flat(ctx: Ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("hubs").values())
    network_id = ctx.args.get("network_id")
    if network_id:
        rows = [h for h in rows if h["network_id"] == network_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/hubs/{hub_id}", [NA])
def get_hub_flat(ctx: Ctx):
    hub = get("hubs", ctx.p("hub_id"))
    if hub is None:
        err("ERR_NOT_FOUND", "Hub not found.")
    return ok(hub)


# ---------------------------------------------------------------------------
# Doors
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/doors", [NA])
def create_door(ctx: Ctx):
    network_id = ctx.p("nid")
    require_network(network_id)
    body = Body(ctx.body)
    door_kind = body.enum("door_kind", ["THEATER", "SPOKE", "GROCERY", "PARTNER"])
    ownership = body.enum("ownership", ["COMPANY", "FRANCHISE"])
    region = body.string("territory_region")
    hub_id = body.optional("hub_id")

    # Territory integrity (validation rung 7, PRD §3.1).
    if door_kind == "THEATER":
        if hub_id is not None:
            err("ERR_TERRITORY_VIOLATION", "A THEATER door is self-supplied and must carry a null hub_id.")
    elif hub_id is not None:
        hub = get("hubs", hub_id)
        if hub is None or hub["network_id"] != network_id:
            err("ERR_NOT_FOUND", "Hub not found.")
        if ownership == "FRANCHISE" and hub["territory_region"] != region:
            err("ERR_TERRITORY_VIOLATION", "A FRANCHISE door's territory must equal its supplying hub's territory.")

    door = create_row("doors", {
        "network_id": network_id,
        "hub_id": hub_id,
        "door_kind": door_kind,
        "ownership": ownership,
        "territory_region": region,
        "door_status": "ACTIVE",
        "credit_balance_cents": 0,
        "open_dispute_count": 0,
    })
    return created(door)


@route("GET", "/networks/{nid}/doors/{door_id}", [NA, HM, RP, DM])
def get_door(ctx: Ctx):
    door = require_door(ctx.p("nid"), ctx.p("door_id"))
    if ctx.role == DM and ctx.user_id != door["id"]:
        err("ERR_UNAUTHORIZED", "A door manager may only view their own door.")
    return ok(door)


@route("GET", "/networks/{nid}/doors", [NA, HM, RP])
def list_doors(ctx: Ctx):
    require_network(ctx.p("nid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("doors", lambda d: d["network_id"] == ctx.p("nid"))
    hub_id = ctx.args.get("hub_id")
    if hub_id:
        rows = [d for d in rows if d.get("hub_id") == hub_id]
    door_kind = ctx.args.get("door_kind")
    if door_kind:
        rows = [d for d in rows if d["door_kind"] == door_kind]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/doors", [NA])
def list_doors_flat(ctx: Ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("doors").values())
    network_id = ctx.args.get("network_id")
    if network_id:
        rows = [d for d in rows if d["network_id"] == network_id]
    hub_id = ctx.args.get("hub_id")
    if hub_id:
        rows = [d for d in rows if d.get("hub_id") == hub_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/doors/{door_id}", [NA])
def get_door_flat(ctx: Ctx):
    door = get("doors", ctx.p("door_id"))
    if door is None:
        err("ERR_NOT_FOUND", "Door not found.")
    return ok(door)


@route("POST", "/networks/{nid}/doors/{door_id}/suspend", [NA])
def suspend_door(ctx: Ctx):
    door = require_door(ctx.p("nid"), ctx.p("door_id"))
    if door["door_status"] == "CLOSED":
        err("ERR_ALREADY_TERMINAL", "The door is CLOSED.")
    if door["door_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Only an ACTIVE door can be suspended.")
    door["door_status"] = "SUSPENDED"
    touch(door)
    recompute_posture(door["network_id"])
    return ok(door)


@route("POST", "/networks/{nid}/doors/{door_id}/reinstate", [NA])
def reinstate_door(ctx: Ctx):
    from services import door_hub_has_working_line
    door = require_door(ctx.p("nid"), ctx.p("door_id"))
    if door["door_status"] == "CLOSED":
        err("ERR_ALREADY_TERMINAL", "The door is CLOSED.")
    if door["door_status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Only a SUSPENDED door can be reinstated.")
    if int(door["open_dispute_count"]) >= 3:
        err("ERR_INVALID_STATE", "The door still has three or more open disputes.")
    if not door_hub_has_working_line(door):
        err("ERR_INVALID_STATE", "The supplying hub has no OPERATIONAL or DEGRADED line.")
    door["door_status"] = "ACTIVE"
    touch(door)
    recompute_posture(door["network_id"])
    return ok(door)


@route("POST", "/networks/{nid}/doors/{door_id}/close", [NA])
def close_door(ctx: Ctx):
    door = require_door(ctx.p("nid"), ctx.p("door_id"))
    if door["door_status"] == "CLOSED":
        err("ERR_ALREADY_TERMINAL", "The door is CLOSED.")
    open_orders = find(
        "fundraisers",
        lambda o: o["door_id"] == door["id"]
        and o["fundraiser_status"] in ("SUBMITTED", "APPROVED", "SCHEDULED", "READY"),
    )
    if open_orders:
        err("ERR_INVALID_STATE", "The door has open fundraiser orders.")
    open_stops = find(
        "stops",
        lambda s: s["door_id"] == door["id"] and s["stop_status"] in ("PENDING", "ARRIVED"),
    )
    if open_stops:
        err("ERR_INVALID_STATE", "The door has pending route stops.")
    open_credits = find(
        "stale_credits",
        lambda c: c["door_id"] == door["id"] and c["credit_state"] in ("PROVISIONAL", "DISPUTED"),
    )
    if open_credits:
        err("ERR_INVALID_STATE", "The door has open stale credits.")
    door["door_status"] = "CLOSED"
    touch(door)
    # Future-dated mix plans are superseded (PRD §3.1).
    today = today_str()
    for plan in find(
        "mix_plans",
        lambda p: p["door_id"] == door["id"]
        and p["mix_plan_status"] in ("DRAFT", "PUBLISHED")
        and p["effective_date"] > today,
    ):
        plan["mix_plan_status"] = "SUPERSEDED"
        touch(plan)
        for line in find("mix_plan_lines", lambda l: l["mix_plan_id"] == plan["id"]):
            if line["allocated_dozens"] != 0:
                line["allocated_dozens"] = 0
                touch(line)
    recompute_posture(door["network_id"])
    return ok(door)


# ---------------------------------------------------------------------------
# Varieties
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/varieties", [NA])
def create_variety(ctx: Ctx):
    require_network(ctx.p("nid"))
    body = Body(ctx.body)
    variety_code = body.string("variety_code")
    collection_kind = body.enum("collection_kind", ["CORE", "SEASONAL", "LICENSED"])
    active_from = body.required("active_from")
    active_until = body.required("active_until")
    from_dt = parse_dt(active_from, "active_from")
    until_dt = parse_dt(active_until, "active_until")
    unit_cost = body.integer("unit_cost_cents", minimum=0)
    if until_dt <= from_dt:
        err("ERR_WINDOW_OVERLAP", "active_until must be strictly later than active_from.")
    status = "EXPIRED" if now() >= until_dt else "ACTIVE"
    variety = create_row("varieties", {
        "network_id": ctx.p("nid"),
        "variety_code": variety_code,
        "collection_kind": collection_kind,
        "active_from": iso_min(from_dt),
        "active_until": iso_min(until_dt),
        "unit_cost_cents": unit_cost,
        "variety_status": status,
        "_active_from_dt": from_dt,
        "_active_until_dt": until_dt,
    })
    return created(variety)


@route("GET", "/networks/{nid}/varieties/{variety_id}", [NA, DM, HM])
def get_variety(ctx: Ctx):
    return ok(require_variety(ctx.p("nid"), ctx.p("variety_id")))


@route("GET", "/networks/{nid}/varieties", [NA, DM, HM])
def list_varieties(ctx: Ctx):
    require_network(ctx.p("nid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("varieties", lambda v: v["network_id"] == ctx.p("nid"))
    kind = ctx.args.get("collection_kind")
    if kind:
        rows = [v for v in rows if v["collection_kind"] == kind]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/varieties", [NA])
def list_varieties_flat(ctx: Ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("varieties").values())
    network_id = ctx.args.get("network_id")
    if network_id:
        rows = [v for v in rows if v["network_id"] == network_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/varieties/{variety_id}", [NA])
def get_variety_flat(ctx: Ctx):
    variety = get("varieties", ctx.p("variety_id"))
    if variety is None:
        err("ERR_NOT_FOUND", "Variety not found.")
    return ok(variety)
