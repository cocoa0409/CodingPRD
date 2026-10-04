"""Routes: equipment lines, production batches, mix plans and lines."""
import math
from datetime import timedelta

from app import created, ok, ok_list, route
from core import (
    create_row, err, find, get, iso, now, page, pagination_args, parse_date,
    table, today_str, touch,
)
from services import (
    Body, FRESHNESS_HOURS, MIN_YIELD_RATE, check_door_ownership,
    effective_dozens, enter_maintenance, maybe_suspend_door_for_hub_lines,
    recompute_posture,
    require_batch, require_door, require_hub, require_line, require_mix_plan,
    require_network, run_mix_allocation,
)

NA = "NetworkAdmin"
HM = "HubManager"
RP = "RoutePlanner"
DM = "DoorManager"

BATCH_TERMINAL = ("COMPLETED", "SHORTFALL", "CANCELLED")


# ---------------------------------------------------------------------------
# Equipment lines
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/lines", [HM])
def create_line(ctx):
    require_hub(ctx.p("nid"), ctx.p("hid"))
    body = Body(ctx.body)
    line_kind = body.enum("line_kind", ["CONTINUOUS_FRYER", "GLAZE_WATERFALL"])
    rated = body.integer("rated_dozens_per_hour", minimum=1)
    interval = body.integer("service_interval_hours", minimum=1)
    line = create_row("lines", {
        "hub_id": ctx.p("hid"),
        "line_kind": line_kind,
        "line_status": "OPERATIONAL",
        "rated_dozens_per_hour": rated,
        "effective_dozens_per_hour": rated,
        "hours_since_service": 0.0,
        "service_interval_hours": interval,
    })
    return created(line)


@route("GET", "/networks/{nid}/hubs/{hid}/lines/{line_id}", [NA, HM])
def get_line(ctx):
    return ok(require_line(ctx.p("nid"), ctx.p("hid"), ctx.p("line_id")))


@route("GET", "/networks/{nid}/hubs/{hid}/lines", [NA, HM, RP])
def list_lines(ctx):
    require_hub(ctx.p("nid"), ctx.p("hid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("lines", lambda l: l["hub_id"] == ctx.p("hid"))
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/lines", [NA, HM])
def list_lines_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("lines").values())
    hub_id = ctx.args.get("hub_id")
    if hub_id:
        rows = [l for l in rows if l["hub_id"] == hub_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/lines/{line_id}", [NA, HM])
def get_line_flat(ctx):
    line = get("lines", ctx.p("line_id"))
    if line is None:
        err("ERR_NOT_FOUND", "Equipment line not found.")
    return ok(line)


@route("POST", "/networks/{nid}/hubs/{hid}/lines/{line_id}/degrade", [HM])
def degrade_line(ctx):
    line = require_line(ctx.p("nid"), ctx.p("hid"), ctx.p("line_id"))
    if line["line_status"] == "DECOMMISSIONED":
        err("ERR_ALREADY_TERMINAL", "The line is DECOMMISSIONED.")
    if line["line_status"] != "OPERATIONAL":
        err("ERR_INVALID_STATE", "Only an OPERATIONAL line can be degraded.")
    if float(line["hours_since_service"]) < 0.5 * float(line["service_interval_hours"]):
        err("ERR_INVALID_STATE",
            "Degradation requires hours_since_service >= 0.5 * service_interval_hours.")
    line["line_status"] = "DEGRADED"
    line["effective_dozens_per_hour"] = effective_dozens(line)
    touch(line)
    return ok(line)


@route("POST", "/networks/{nid}/hubs/{hid}/lines/{line_id}/maintenance/start", [HM])
def start_maintenance(ctx):
    line = require_line(ctx.p("nid"), ctx.p("hid"), ctx.p("line_id"))
    if line["line_status"] == "DECOMMISSIONED":
        err("ERR_ALREADY_TERMINAL", "The line is DECOMMISSIONED.")
    if line["line_status"] == "MAINTENANCE":
        err("ERR_INVALID_STATE", "The line is already in MAINTENANCE.")
    running = find(
        "batches",
        lambda b: b["equipment_line_id"] == line["id"] and b["batch_status"] == "RUNNING",
    )
    if running:
        err("ERR_INVALID_STATE", "A batch is RUNNING on this line.")
    enter_maintenance(line)
    return ok(line)


@route("POST", "/networks/{nid}/hubs/{hid}/lines/{line_id}/maintenance/complete", [HM])
def complete_maintenance(ctx):
    line = require_line(ctx.p("nid"), ctx.p("hid"), ctx.p("line_id"))
    if line["line_status"] == "DECOMMISSIONED":
        err("ERR_ALREADY_TERMINAL", "The line is DECOMMISSIONED.")
    if line["line_status"] != "MAINTENANCE":
        err("ERR_INVALID_STATE", "The line is not in MAINTENANCE.")
    line["line_status"] = "OPERATIONAL"
    line["hours_since_service"] = 0.0
    line["effective_dozens_per_hour"] = line["rated_dozens_per_hour"]
    touch(line)
    hub = get("hubs", line["hub_id"])
    recompute_posture(hub["network_id"])
    return ok(line)


@route("POST", "/networks/{nid}/hubs/{hid}/lines/{line_id}/decommission", [HM])
def decommission_line(ctx):
    line = require_line(ctx.p("nid"), ctx.p("hid"), ctx.p("line_id"))
    if line["line_status"] == "DECOMMISSIONED":
        err("ERR_ALREADY_TERMINAL", "The line is DECOMMISSIONED.")
    if line["line_status"] == "MAINTENANCE":
        err("ERR_INVALID_STATE", "A line in MAINTENANCE cannot be decommissioned.")
    active = find(
        "batches",
        lambda b: b["equipment_line_id"] == line["id"]
        and b["batch_status"] in ("SCHEDULED", "COMMITTED", "RUNNING"),
    )
    if active:
        err("ERR_INVALID_STATE",
            "The line has batches in SCHEDULED, COMMITTED, or RUNNING.")
    line["line_status"] = "DECOMMISSIONED"
    line["effective_dozens_per_hour"] = 0
    touch(line)
    hub = get("hubs", line["hub_id"])
    recompute_posture(hub["network_id"])
    maybe_suspend_door_for_hub_lines(hub["id"])
    return ok(line)


# ---------------------------------------------------------------------------
# Production batches
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/hubs/{hid}/batches", [HM])
def create_batch(ctx):
    hub = require_hub(ctx.p("nid"), ctx.p("hid"))
    body = Body(ctx.body)
    line_id = body.required("equipment_line_id")
    line = get("lines", line_id)
    if line is None or line["hub_id"] != hub["id"]:
        err("ERR_CROSS_SCOPE_REFERENCE",
            "equipment_line_id must reference a line of this hub.")
    production_date = parse_date(body.required("production_date"), "production_date")
    planned = body.integer("planned_dozens", minimum=1)
    batch = create_row("batches", {
        "hub_id": hub["id"],
        "equipment_line_id": line_id,
        "production_date": production_date,
        "planned_dozens": planned,
        "produced_dozens": None,
        "batch_status": "SCHEDULED",
        "fresh_until": None,
        "yield_rate": None,
    })
    return created(batch)


@route("GET", "/networks/{nid}/hubs/{hid}/batches/{batch_id}", [NA, HM, RP])
def get_batch(ctx):
    return ok(require_batch(ctx.p("nid"), ctx.p("hid"), ctx.p("batch_id")))


@route("GET", "/networks/{nid}/hubs/{hid}/batches", [NA, HM, RP])
def list_batches(ctx):
    require_hub(ctx.p("nid"), ctx.p("hid"))
    limit, offset = pagination_args(ctx.args)
    rows = find("batches", lambda b: b["hub_id"] == ctx.p("hid"))
    production_date = ctx.args.get("production_date")
    if production_date:
        rows = [b for b in rows if b["production_date"] == production_date]
    status = ctx.args.get("batch_status")
    if status:
        rows = [b for b in rows if b["batch_status"] == status]
    line_id = ctx.args.get("equipment_line_id")
    if line_id:
        rows = [b for b in rows if b["equipment_line_id"] == line_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/batches", [NA])
def list_batches_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("batches").values())
    hub_id = ctx.args.get("hub_id")
    if hub_id:
        rows = [b for b in rows if b["hub_id"] == hub_id]
    line_id = ctx.args.get("equipment_line_id")
    if line_id:
        rows = [b for b in rows if b["equipment_line_id"] == line_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/batches/{batch_id}", [NA])
def get_batch_flat(ctx):
    batch = get("batches", ctx.p("batch_id"))
    if batch is None:
        err("ERR_NOT_FOUND", "Production batch not found.")
    return ok(batch)


@route("POST", "/networks/{nid}/hubs/{hid}/batches/{batch_id}/commit", [HM])
def commit_batch(ctx):
    hub = require_hub(ctx.p("nid"), ctx.p("hid"))
    batch = get("batches", ctx.p("batch_id"))
    if batch is None or batch["hub_id"] != hub["id"]:
        err("ERR_NOT_FOUND", "Production batch not found.")
    # State admissibility (rung 4).
    if batch["batch_status"] in BATCH_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The batch is in a terminal state.")
    if batch["batch_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Only a SCHEDULED batch can be committed.")
    line = get("lines", batch["equipment_line_id"])
    if line["line_status"] not in ("OPERATIONAL", "DEGRADED"):
        err("ERR_INVALID_STATE",
            "The batch's line is not OPERATIONAL or DEGRADED.")
    # Capacity (rung 9) before OCC (rung 11).
    if int(hub["committed_dozens_today"]) + int(batch["planned_dozens"]) > int(hub["daily_capacity_dozens"]):
        err("ERR_CAPACITY_EXCEEDED", "The hub's daily capacity would be exceeded.")
    network = get("networks", hub["network_id"])
    if network["network_posture"] not in ("OPEN", "DEGRADED"):
        err("ERR_INVALID_STATE", "The network posture does not permit batch commits.")
    # OCC (rung 11).
    expected = Body(ctx.body).integer("expected_hub_version")
    if expected != int(hub["version"]):
        err("ERR_STALE_VERSION", "expected_hub_version does not match the hub's current version.")
    batch["batch_status"] = "COMMITTED"
    touch(batch)
    hub["committed_dozens_today"] = int(hub["committed_dozens_today"]) + int(batch["planned_dozens"])
    touch(hub)
    return ok(batch)


@route("POST", "/networks/{nid}/hubs/{hid}/batches/{batch_id}/start", [HM])
def start_batch(ctx):
    hub = require_hub(ctx.p("nid"), ctx.p("hid"))
    batch = get("batches", ctx.p("batch_id"))
    if batch is None or batch["hub_id"] != hub["id"]:
        err("ERR_NOT_FOUND", "Production batch not found.")
    if batch["batch_status"] in BATCH_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The batch is in a terminal state.")
    if batch["batch_status"] != "COMMITTED":
        err("ERR_INVALID_STATE", "Only a COMMITTED batch can be started.")
    line = get("lines", batch["equipment_line_id"])
    if line["line_status"] not in ("OPERATIONAL", "DEGRADED"):
        err("ERR_INVALID_STATE", "The batch's line is not OPERATIONAL or DEGRADED.")
    busy = find(
        "batches",
        lambda b: b["equipment_line_id"] == line["id"]
        and b["batch_status"] == "RUNNING" and b["id"] != batch["id"],
    )
    if busy:
        err("ERR_LINE_BUSY", "Another batch is RUNNING on this line.")
    batch["batch_status"] = "RUNNING"
    touch(batch)
    return ok(batch)


@route("POST", "/networks/{nid}/hubs/{hid}/batches/{batch_id}/complete", [HM])
def complete_batch(ctx):
    hub = require_hub(ctx.p("nid"), ctx.p("hid"))
    batch = get("batches", ctx.p("batch_id"))
    if batch is None or batch["hub_id"] != hub["id"]:
        err("ERR_NOT_FOUND", "Production batch not found.")
    if batch["batch_status"] in BATCH_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The batch is in a terminal state.")
    if batch["batch_status"] != "RUNNING":
        err("ERR_INVALID_STATE", "Only a RUNNING batch can be completed.")
    produced = Body(ctx.body).integer("produced_dozens", minimum=0)
    planned = int(batch["planned_dozens"])
    batch["produced_dozens"] = produced
    line = get("lines", batch["equipment_line_id"])

    if produced >= float(MIN_YIELD_RATE) * planned:
        batch["batch_status"] = "COMPLETED"
        completion = now()
        fresh_until = completion + timedelta(hours=FRESHNESS_HOURS)
        batch["fresh_until"] = iso(fresh_until)
        batch["_fresh_until_dt"] = fresh_until
        batch["yield_rate"] = produced / planned
        effective = int(line["effective_dozens_per_hour"])
        if effective > 0:
            line["hours_since_service"] = float(line["hours_since_service"]) + planned / effective
            touch(line)
        hub["committed_dozens_today"] = max(
            0, int(hub["committed_dozens_today"]) - planned)
        touch(hub)
        touch(batch)
        run_mix_allocation(hub["id"], batch["production_date"])
    else:
        batch["batch_status"] = "SHORTFALL"
        batch["yield_rate"] = produced / planned
        hub["committed_dozens_today"] = max(
            0, int(hub["committed_dozens_today"]) - planned)
        touch(hub)
        touch(batch)
        run_mix_allocation(hub["id"], batch["production_date"])
        recompute_posture(hub["network_id"])
    return ok(batch)


@route("POST", "/networks/{nid}/hubs/{hid}/batches/{batch_id}/cancel", [HM])
def cancel_batch(ctx):
    hub = require_hub(ctx.p("nid"), ctx.p("hid"))
    batch = get("batches", ctx.p("batch_id"))
    if batch is None or batch["hub_id"] != hub["id"]:
        err("ERR_NOT_FOUND", "Production batch not found.")
    if batch["batch_status"] in BATCH_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "The batch is in a terminal state.")
    if batch["batch_status"] == "RUNNING":
        err("ERR_INVALID_STATE", "A RUNNING batch cannot be cancelled.")
    if batch["batch_status"] == "COMMITTED":
        hub["committed_dozens_today"] = max(
            0, int(hub["committed_dozens_today"]) - int(batch["planned_dozens"]))
        touch(hub)
    batch["batch_status"] = "CANCELLED"
    touch(batch)
    return ok(batch)


# ---------------------------------------------------------------------------
# Mix plans and lines
# ---------------------------------------------------------------------------
@route("POST", "/networks/{nid}/doors/{did}/mix-plans", [DM])
def create_mix_plan(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    body = Body(ctx.body)
    effective_date = parse_date(body.required("effective_date"), "effective_date")
    plan = create_row("mix_plans", {
        "door_id": door["id"],
        "effective_date": effective_date,
        "mix_plan_status": "DRAFT",
        "total_planned_dozens": 0,
        "license_quota_dozens": 0,
    })
    return created(plan)


@route("GET", "/networks/{nid}/doors/{did}/mix-plans/{plan_id}", [NA, DM])
def get_mix_plan(ctx):
    plan = require_mix_plan(ctx.p("nid"), ctx.p("did"), ctx.p("plan_id"))
    check_door_ownership(ctx, ctx.p("did"))
    return ok(plan)


@route("GET", "/networks/{nid}/doors/{did}/mix-plans", [NA, DM])
def list_mix_plans(ctx):
    require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, ctx.p("did"))
    limit, offset = pagination_args(ctx.args)
    rows = find("mix_plans", lambda p: p["door_id"] == ctx.p("did"))
    status = ctx.args.get("mix_plan_status")
    if status:
        rows = [p for p in rows if p["mix_plan_status"] == status]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("POST", "/networks/{nid}/doors/{did}/mix-plans/{plan_id}/lines", [DM])
def upsert_mix_plan_line(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    plan = get("mix_plans", ctx.p("plan_id"))
    if plan is None or plan["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Mix plan not found.")
    if plan["mix_plan_status"] in ("LOCKED", "SUPERSEDED"):
        err("ERR_MIX_PLAN_LOCKED", "The mix plan no longer accepts line upserts.")
    if plan["mix_plan_status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Only a DRAFT plan accepts line upserts.")
    body = Body(ctx.body)
    variety_id = body.required("variety_id")
    variety = get("varieties", variety_id)
    if variety is None or variety["network_id"] != ctx.p("nid"):
        err("ERR_CROSS_SCOPE_REFERENCE",
            "variety_id must reference a variety of this network.")
    planned = body.integer("planned_dozens", minimum=0)

    existing = None
    for line in find("mix_plan_lines", lambda l: l["mix_plan_id"] == plan["id"]):
        if line["variety_id"] == variety_id:
            existing = line
            break
    if existing is None:
        line = create_row("mix_plan_lines", {
            "mix_plan_id": plan["id"],
            "variety_id": variety_id,
            "planned_dozens": planned,
            "allocated_dozens": 0,
        })
    else:
        line = existing
        line["planned_dozens"] = planned
        touch(line)

    lines = find("mix_plan_lines", lambda l: l["mix_plan_id"] == plan["id"])
    total = sum(int(l["planned_dozens"]) for l in lines)
    licensed = sum(
        int(l["planned_dozens"]) for l in lines
        if get("varieties", l["variety_id"])
        and get("varieties", l["variety_id"])["collection_kind"] == "LICENSED"
    )
    plan["total_planned_dozens"] = total
    plan["license_quota_dozens"] = licensed
    touch(plan)
    return created(line)


@route("GET", "/networks/{nid}/doors/{did}/mix-plans/{plan_id}/lines", [NA, DM])
def list_mix_plan_lines(ctx):
    require_mix_plan(ctx.p("nid"), ctx.p("did"), ctx.p("plan_id"))
    check_door_ownership(ctx, ctx.p("did"))
    limit, offset = pagination_args(ctx.args)
    rows = find("mix_plan_lines", lambda l: l["mix_plan_id"] == ctx.p("plan_id"))
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/mix-plans", [NA])
def list_mix_plans_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("mix_plans").values())
    door_id = ctx.args.get("door_id")
    if door_id:
        rows = [p for p in rows if p["door_id"] == door_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/mix-plans/{plan_id}", [NA])
def get_mix_plan_flat(ctx):
    plan = get("mix_plans", ctx.p("plan_id"))
    if plan is None:
        err("ERR_NOT_FOUND", "Mix plan not found.")
    return ok(plan)


@route("GET", "/networks/mix-plan-lines", [NA])
def list_mix_plan_lines_flat(ctx):
    limit, offset = pagination_args(ctx.args)
    rows = list(table("mix_plan_lines").values())
    plan_id = ctx.args.get("mix_plan_id")
    if plan_id:
        rows = [l for l in rows if l["mix_plan_id"] == plan_id]
    variety_id = ctx.args.get("variety_id")
    if variety_id:
        rows = [l for l in rows if l["variety_id"] == variety_id]
    rows, meta = page(rows, limit, offset)
    return ok_list(rows, meta)


@route("GET", "/networks/mix-plan-lines/{line_id}", [NA])
def get_mix_plan_line_flat(ctx):
    line = get("mix_plan_lines", ctx.p("line_id"))
    if line is None:
        err("ERR_NOT_FOUND", "Mix plan line not found.")
    return ok(line)


@route("POST", "/networks/{nid}/doors/{did}/mix-plans/{plan_id}/publish", [DM])
def publish_mix_plan(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    plan = get("mix_plans", ctx.p("plan_id"))
    if plan is None or plan["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Mix plan not found.")
    # State admissibility (rung 4).
    if plan["mix_plan_status"] in ("SUPERSEDED", "LOCKED"):
        err("ERR_ALREADY_TERMINAL", "The mix plan is in a terminal state.")
    if plan["mix_plan_status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Only a DRAFT plan can be published.")
    if door["door_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "The door is not ACTIVE.")
    # Variety freshness for the plan's effective date (PRD §3.4).
    lines = find("mix_plan_lines", lambda l: l["mix_plan_id"] == plan["id"])
    eff_start = parse_date(plan["effective_date"], "effective_date")
    from datetime import datetime, timezone
    eff_dt = datetime.fromisoformat(eff_start + "T00:00:00+00:00").astimezone(timezone.utc)
    for line in lines:
        variety = get("varieties", line["variety_id"])
        if variety is None:
            err("ERR_VARIETY_EXPIRED", "A line references a missing variety.")
        if eff_dt >= variety["_active_until_dt"] or eff_dt < variety["_active_from_dt"]:
            err("ERR_VARIETY_EXPIRED",
                "A line's variety is not ACTIVE for the plan's effective date.")
    # License quota (rung 8).
    total = int(plan["total_planned_dozens"])
    if total > 0 and int(plan["license_quota_dozens"]) > math.floor(0.25 * total):
        err("ERR_LICENSE_QUOTA_EXCEEDED",
            "LICENSED varieties exceed 25 percent of the plan.")
    # OCC (rung 11).
    expected = Body(ctx.body).integer("expected_mix_plan_version")
    if expected != int(plan["version"]):
        err("ERR_STALE_VERSION",
            "expected_mix_plan_version does not match the plan's current version.")
    # Supersede the prior PUBLISHED plan for the same door and date.
    prior = find(
        "mix_plans",
        lambda p: p["door_id"] == door["id"]
        and p["effective_date"] == plan["effective_date"]
        and p["mix_plan_status"] == "PUBLISHED"
        and p["id"] != plan["id"],
    )
    for old in prior:
        old["mix_plan_status"] = "SUPERSEDED"
        touch(old)
        for line in find("mix_plan_lines", lambda l: l["mix_plan_id"] == old["id"]):
            if line["allocated_dozens"] != 0:
                line["allocated_dozens"] = 0
                touch(line)
    plan["mix_plan_status"] = "PUBLISHED"
    touch(plan)
    return ok(plan)


@route("POST", "/networks/{nid}/doors/{did}/mix-plans/{plan_id}/lock", [DM])
def lock_mix_plan(ctx):
    door = require_door(ctx.p("nid"), ctx.p("did"))
    check_door_ownership(ctx, door["id"])
    plan = get("mix_plans", ctx.p("plan_id"))
    if plan is None or plan["door_id"] != door["id"]:
        err("ERR_NOT_FOUND", "Mix plan not found.")
    if plan["mix_plan_status"] in ("SUPERSEDED", "LOCKED"):
        err("ERR_ALREADY_TERMINAL", "The mix plan is in a terminal state.")
    if plan["mix_plan_status"] != "PUBLISHED":
        err("ERR_INVALID_STATE", "Only a PUBLISHED plan can be locked.")
    covering = find(
        "stops",
        lambda s: s["door_id"] == door["id"]
        and get("routes", s["route_id"]) is not None
        and get("routes", s["route_id"])["route_status"] in ("LOCKED", "DISPATCHED")
        and get("routes", s["route_id"])["service_date"] == plan["effective_date"],
    )
    if not covering:
        err("ERR_INVALID_STATE",
            "No route stop for this door on a LOCKED or DISPATCHED route for the effective date.")
    plan["mix_plan_status"] = "LOCKED"
    touch(plan)
    return ok(plan)
