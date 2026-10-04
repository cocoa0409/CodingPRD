"""Distribution centers, DC assignments, route plans, opening plans."""
from flask import Blueprint, request
from datetime import timedelta

from db import DB, parse_iso
from errors import ApiError, err_invalid_request, err_validation
from middleware import require_roles, get_body, req_str, opt_int, req_bool
from response import success, parse_pagination, paginate
from services import (base_entity, touch, compute_stem_cost, compute_route_plan,
                      compute_labor, append_event, recompute_capital, fmt_dt)
from helpers import (pub, pub_list, sorted_by_creation, body_rollout, require_active,
                     check_name_unique, parse_dt_field)

bp = Blueprint("distribution", __name__)

ALL = ("PROGRAM_ADMIN", "REAL_ESTATE_MANAGER", "NETWORK_PLANNER",
       "OPERATIONS_LEAD", "FINANCE_ANALYST")
NP = ("NETWORK_PLANNER",)
OL = ("OPERATIONS_LEAD",)


# ---- distribution centers -------------------------------------------------------

@bp.post("/rollouts/distribution-centers")
def create_dc():
    require_roles(*NP)
    body = get_body()
    program = body_rollout(body)
    name = req_str(body, "name")
    if "store_capacity" not in body or body["store_capacity"] is None:
        raise err_invalid_request("store_capacity is required")
    cap = opt_int(body, "store_capacity")
    if cap <= 0:
        raise err_validation("store_capacity must be > 0")
    check_name_unique(DB.dcs, program["id"], name, "distribution center")
    d = base_entity()
    d.update({
        "rollout_program_id": program["id"],
        "name": name,
        "store_capacity": cap,
        "assigned_store_count": 0,
        "remaining_capacity": cap,
    })
    DB.dcs[d["id"]] = d
    return success(pub(d), 201)


@bp.get("/rollouts/distribution-centers")
def list_dcs():
    require_roles(*ALL)
    items = list(DB.dcs.values())
    pid = request.args.get("rollout_program_id")
    if pid is not None:
        items = [d for d in items if d["rollout_program_id"] == pid]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(request.args)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/distribution-centers/<dcid>")
def get_dc_by_id(dcid):
    require_roles(*ALL)
    from helpers import get_dc
    return success(pub(get_dc(dcid)), 200)


# ---- dc assignments --------------------------------------------------------------

@bp.post("/rollouts/dc-assignments")
def create_assignment():
    require_roles(*NP)
    body = get_body()
    program = body_rollout(body)
    store_id = body.get("store_id")
    if not isinstance(store_id, str):
        raise err_invalid_request("store_id is required")
    dc_id = body.get("distribution_center_id")
    if not isinstance(dc_id, str):
        raise err_invalid_request("distribution_center_id is required")
    if "stem_miles" not in body or body["stem_miles"] is None:
        raise err_invalid_request("stem_miles is required")
    stem = body["stem_miles"]
    if isinstance(stem, bool) or not isinstance(stem, (int, float)):
        raise err_invalid_request("stem_miles must be a number")
    if stem <= 0:
        raise err_validation("stem_miles must be > 0")
    if "deliveries_per_week" not in body or body["deliveries_per_week"] is None:
        raise err_invalid_request("deliveries_per_week is required")
    dpw = opt_int(body, "deliveries_per_week")
    if dpw < 1:
        raise err_validation("deliveries_per_week must be >= 1")

    store = DB.stores.get(store_id)
    if store is None or store["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "store not found in program")
    dc = DB.dcs.get(dc_id)
    if dc is None or dc["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "distribution center not found in program")
    if dc["remaining_capacity"] < 1:
        raise ApiError("ERR_DC_CAPACITY_EXCEEDED",
                       "distribution center has no remaining store capacity")

    for a in DB.dc_assignments.values():
        if a["store_id"] == store_id and a["status"] == "ACTIVE":
            a["status"] = "SUPERSEDED"
            touch(a)
            old_dc = DB.dcs.get(a["distribution_center_id"])
            if old_dc is not None:
                old_dc["assigned_store_count"] -= 1
                old_dc["remaining_capacity"] = (
                    old_dc["store_capacity"] - old_dc["assigned_store_count"])
                touch(old_dc)

    cost = compute_stem_cost(store, stem, dpw)
    a = base_entity()
    a.update({
        "rollout_program_id": program["id"],
        "store_id": store_id,
        "distribution_center_id": dc_id,
        "stem_miles": stem,
        "deliveries_per_week": dpw,
        "status": "ACTIVE",
        "stem_cost_cents_per_week": cost,
    })
    DB.dc_assignments[a["id"]] = a
    dc["assigned_store_count"] += 1
    dc["remaining_capacity"] = dc["store_capacity"] - dc["assigned_store_count"]
    touch(dc)
    store["stem_miles"] = stem
    touch(store)
    return success(pub(a), 201)


@bp.get("/rollouts/dc-assignments")
def list_assignments():
    require_roles(*ALL)
    items = list(DB.dc_assignments.values())
    q = request.args
    if q.get("store_id") is not None:
        items = [a for a in items if a["store_id"] == q["store_id"]]
    if q.get("distribution_center_id") is not None:
        items = [a for a in items if a["distribution_center_id"] == q["distribution_center_id"]]
    if q.get("status") is not None:
        items = [a for a in items if a["status"] == q["status"]]
    if q.get("rollout_program_id") is not None:
        items = [a for a in items if a.get("rollout_program_id") == q["rollout_program_id"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/dc-assignments/<asgid>")
def get_assignment_by_id(asgid):
    require_roles(*ALL)
    from helpers import get_assignment
    return success(pub(get_assignment(asgid)), 200)


# ---- route plans --------------------------------------------------------------------

@bp.post("/rollouts/route-plans")
def create_route_plan():
    require_roles(*NP)
    body = get_body()
    program = body_rollout(body)
    store_id = body.get("store_id")
    if not isinstance(store_id, str):
        raise err_invalid_request("store_id is required")
    store = DB.stores.get(store_id)
    if store is None or store["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "store not found in program")
    active_asg = None
    for a in DB.dc_assignments.values():
        if a["store_id"] == store_id and a["status"] == "ACTIVE":
            active_asg = a
            break
    if active_asg is None:
        raise ApiError("ERR_NO_ACTIVE_ASSIGNMENT",
                       "route planning requires an ACTIVE DCAssignment")
    calc = compute_route_plan(store)
    for rp in DB.route_plans.values():
        if rp["store_id"] == store_id and rp["status"] == "ACTIVE":
            rp["status"] = "SUPERSEDED"
            touch(rp)
    rp = base_entity()
    rp.update({
        "rollout_program_id": program["id"],
        "store_id": store_id,
        "status": "ACTIVE",
        **calc,
    })
    DB.route_plans[rp["id"]] = rp
    return success(pub(rp), 201)


@bp.get("/rollouts/route-plans")
def list_route_plans():
    require_roles(*ALL)
    items = list(DB.route_plans.values())
    q = request.args
    if q.get("store_id") is not None:
        items = [r for r in items if r["store_id"] == q["store_id"]]
    if q.get("status") is not None:
        items = [r for r in items if r["status"] == q["status"]]
    if q.get("rollout_program_id") is not None:
        items = [r for r in items if r.get("rollout_program_id") == q["rollout_program_id"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/route-plans/<rpid>")
def get_route_plan_by_id(rpid):
    require_roles(*ALL)
    from helpers import get_route_plan
    return success(pub(get_route_plan(rpid)), 200)


# ---- opening plans --------------------------------------------------------------------

def _agreement_for_store_in(store_id, statuses):
    for ag in DB.agreements.values():
        if ag["store_id"] == store_id and ag["status"] in statuses:
            return ag
    return None


@bp.post("/rollouts/opening-plans")
def create_opening_plan():
    require_roles(*OL)
    body = get_body()
    program = body_rollout(body)
    store_id = body.get("store_id")
    if not isinstance(store_id, str):
        raise err_invalid_request("store_id is required")
    if "opening_date" not in body or body["opening_date"] is None:
        raise err_invalid_request("opening_date is required")
    opening = parse_dt_field(body["opening_date"], "opening_date")
    if "peak_season" not in body or body["peak_season"] is None:
        raise err_invalid_request("peak_season is required")
    peak = req_bool(body, "peak_season")

    store = DB.stores.get(store_id)
    if store is None or store["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "store not found in program")

    require_active(program)

    clock = DB.get_clock(program["id"])
    if opening < clock + timedelta(days=45):
        raise ApiError("ERR_OPENING_TOO_EARLY",
                       "opening_date must be at least 45 days in the future")

    ag = _agreement_for_store_in(store_id, ("EXECUTED",))
    if ag is None:
        raise ApiError("ERR_STORE_PRECONDITION",
                       "opening plan requires an EXECUTED agreement")
    committed = parse_iso(ag["committed_delivery_date"])
    if committed > opening + timedelta(days=30):
        raise ApiError("ERR_STORE_PRECONDITION",
                       "committed_delivery_date must be at most 30 days after opening_date")

    for op in DB.opening_plans.values():
        if op["store_id"] == store_id and op["status"] in ("PLANNED", "LOCKED"):
            raise ApiError("ERR_DUPLICATE_ACTIVE",
                           "store already has a live opening plan")

    hours, cost = compute_labor(store["format_type"], peak)
    op = base_entity()
    op.update({
        "rollout_program_id": program["id"],
        "store_id": store_id,
        "opening_date": fmt_dt(opening),
        "fixture_kit_ship_date": fmt_dt(opening - timedelta(days=21)),
        "inventory_push_date": fmt_dt(opening - timedelta(days=10)),
        "peak_season": peak,
        "labor_hours": hours,
        "labor_cost_cents": cost,
        "status": "PLANNED",
    })
    DB.opening_plans[op["id"]] = op
    store["opening_date"] = fmt_dt(opening)
    touch(store)
    return success(pub(op), 201)


@bp.get("/rollouts/opening-plans")
def list_opening_plans():
    require_roles(*ALL)
    items = list(DB.opening_plans.values())
    q = request.args
    if q.get("store_id") is not None:
        items = [o for o in items if o["store_id"] == q["store_id"]]
    if q.get("status") is not None:
        items = [o for o in items if o["status"] == q["status"]]
    if q.get("rollout_program_id") is not None:
        items = [o for o in items if o.get("rollout_program_id") == q["rollout_program_id"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/opening-plans/<opid>")
def get_opening_plan_by_id(opid):
    require_roles(*ALL)
    from helpers import get_opening_plan
    return success(pub(get_opening_plan(opid)), 200)


@bp.post("/rollouts/opening-plans/<opid>/lock")
def lock_opening_plan(opid):
    require_roles(*OL)
    from helpers import get_opening_plan
    op = get_opening_plan(opid)
    body = get_body()
    body_rollout(body, expected_pid=op["rollout_program_id"])
    if op["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "only a PLANNED plan may be locked")
    store = DB.stores[op["store_id"]]
    if store["status"] != "SITE_CONTROL":
        raise ApiError("ERR_OPENING_PLAN_STATE",
                       "opening-plan lock requires store status SITE_CONTROL")
    ag = _agreement_for_store_in(op["store_id"], ("EXECUTED",))
    if ag is None:
        raise ApiError("ERR_STORE_PRECONDITION",
                       "opening-plan lock requires an EXECUTED agreement")
    committed = parse_iso(ag["committed_delivery_date"])
    fixture = parse_iso(op["fixture_kit_ship_date"])
    if committed > fixture:
        raise ApiError("ERR_FIXTURE_LEAD_TIME",
                       "committed_delivery_date is after fixture_kit_ship_date")
    op["status"] = "LOCKED"
    touch(op)
    return success(pub(op), 200)


@bp.post("/rollouts/opening-plans/<opid>/unlock")
def unlock_opening_plan(opid):
    require_roles(*OL)
    from helpers import get_opening_plan
    op = get_opening_plan(opid)
    body = get_body()
    body_rollout(body, expected_pid=op["rollout_program_id"])
    if op["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "only a LOCKED plan may be unlocked")
    store = DB.stores[op["store_id"]]
    if store["status"] not in ("SITE_CONTROL", "PROPOSED"):
        raise ApiError("ERR_INVALID_STATE",
                       "unlock requires store status SITE_CONTROL or PROPOSED")
    op["status"] = "PLANNED"
    touch(op)
    return success(pub(op), 200)


@bp.post("/rollouts/opening-plans/<opid>/execute")
def execute_opening_plan(opid):
    require_roles(*OL)
    from helpers import get_opening_plan
    op = get_opening_plan(opid)
    body = get_body()
    program = body_rollout(body, expected_pid=op["rollout_program_id"])
    if op["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "only a LOCKED plan may be executed")
    store = DB.stores[op["store_id"]]
    if store["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "store must be DELIVERED to execute opening")
    ag = _agreement_for_store_in(op["store_id"], ("DELIVERED",))
    if ag is None:
        raise ApiError("ERR_INVALID_STATE",
                       "the delivering agreement must be in DELIVERED status")
    clock = DB.get_clock(program["id"])
    opening = parse_iso(op["opening_date"])
    if clock < opening - timedelta(days=3):
        raise ApiError("ERR_OPENING_TOO_EARLY",
                       "clock must be at least opening_date - 3 days")
    op["status"] = "EXECUTED"
    touch(op)
    ag["status"] = "COMPLETED"
    touch(ag)
    store["status"] = "OPEN"
    touch(store)
    append_event(program, "STORE_OPENED", store_id=store["id"],
                 payload={"opening_date": op["opening_date"]})
    recompute_capital(program)
    touch(program)
    return success(pub(op), 200)
