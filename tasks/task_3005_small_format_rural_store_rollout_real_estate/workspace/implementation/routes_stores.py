"""Stores, developers, site control agreements."""
from flask import Blueprint, request

from db import DB
from errors import ApiError, err_invalid_request, err_validation
from middleware import require_roles, get_body, req_str, opt_int
from response import success, parse_pagination, paginate
from services import (base_entity, touch, select_format, compute_penalty,
                      recompute_capital, fmt_dt, WEEKLY_CASES, BUILD_COST)
from helpers import (pub, pub_list, sorted_by_creation, get_store, body_rollout,
                     require_active, check_name_unique, parse_dt_field)

bp = Blueprint("stores", __name__)

ALL = ("PROGRAM_ADMIN", "REAL_ESTATE_MANAGER", "NETWORK_PLANNER",
       "OPERATIONS_LEAD", "FINANCE_ANALYST")
ADMIN = ("PROGRAM_ADMIN",)
REM = ("REAL_ESTATE_MANAGER",)
NP = ("NETWORK_PLANNER",)
FA = ("FINANCE_ANALYST",)

FORMATS = ("TRADITIONAL", "DG_FRESH", "DG_MARKET")


def _open_agreement_for_store(store_id):
    for ag in DB.agreements.values():
        if ag["store_id"] == store_id and ag["status"] not in ("TERMINATED", "COMPLETED"):
            return ag
    return None


# ---- stores ------------------------------------------------------------------

@bp.post("/rollouts/stores")
def create_store():
    require_roles(*ADMIN)
    body = get_body()
    program = body_rollout(body)
    taid = body.get("trade_area_id")
    if not isinstance(taid, str):
        raise err_invalid_request("trade_area_id is required")
    name = req_str(body, "name")
    is_existing = body.get("is_existing", False)
    if not isinstance(is_existing, bool):
        raise err_invalid_request("is_existing must be a boolean")

    fmt = None
    existing_store_id = None
    open_sales = None
    if is_existing:
        fmt = body.get("format_type")
        if fmt is None:
            raise err_invalid_request("format_type is required for existing stores")
        if fmt not in FORMATS:
            raise err_invalid_request("format_type must be one of TRADITIONAL, DG_FRESH, DG_MARKET")
        if "existing_store_id" in body and body["existing_store_id"] is not None:
            existing_store_id = body["existing_store_id"]
            if not isinstance(existing_store_id, str):
                raise err_invalid_request("existing_store_id must be a string")
            if existing_store_id not in DB.stores:
                raise ApiError("ERR_BAD_REFERENCE", "existing_store_id does not resolve")
        if "open_year_sales_cents" in body and body["open_year_sales_cents"] is not None:
            open_sales = opt_int(body, "open_year_sales_cents")

    require_active(program)

    ta = DB.trade_areas.get(taid)
    if ta is None or ta["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "trade area not found in program")

    check_name_unique(DB.stores, program["id"], name, "store")

    if is_existing:
        status = "EXISTING"
    else:
        if ta["status"] != "QUALIFIED":
            raise ApiError("ERR_TRADE_AREA_NOT_QUALIFIED",
                           "store creation requires a QUALIFIED trade area")
        status = "PROPOSED"

    s = base_entity()
    s.update({
        "rollout_program_id": program["id"],
        "trade_area_id": ta["id"],
        "name": name,
        "format_type": fmt,
        "existing_store_id": existing_store_id,
        "status": status,
        "stem_miles": 0,
        "weekly_case_volume_base": None,
        "projected_revenue_cents": None,
        "volume_index": 1.0,
        "build_cost_cents": None,
        "opening_date": None,
        "open_year_sales_cents": open_sales,
    })
    DB.stores[s["id"]] = s
    return success(pub(s), 201)


@bp.get("/rollouts/stores")
def list_stores():
    require_roles(*ALL)
    items = list(DB.stores.values())
    q = request.args
    if q.get("rollout_program_id") is not None:
        items = [s for s in items if s["rollout_program_id"] == q["rollout_program_id"]]
    if q.get("status") is not None:
        items = [s for s in items if s["status"] == q["status"]]
    if q.get("format_type") is not None:
        items = [s for s in items if s["format_type"] == q["format_type"]]
    if q.get("trade_area_id") is not None:
        items = [s for s in items if s["trade_area_id"] == q["trade_area_id"]]
    if q.get("existing_store_id") is not None:
        items = [s for s in items if s.get("existing_store_id") == q["existing_store_id"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/stores/<sid>")
def get_store_by_id(sid):
    require_roles(*ALL)
    return success(pub(get_store(sid)), 200)


@bp.patch("/rollouts/stores/<sid>")
def update_store(sid):
    require_roles(*NP)
    store = get_store(sid)
    body = get_body()
    body_rollout(body, expected_pid=store["rollout_program_id"])
    if "volume_index" not in body or body["volume_index"] is None:
        raise err_invalid_request("volume_index is required")
    vi = body["volume_index"]
    if isinstance(vi, bool) or not isinstance(vi, (int, float)):
        raise err_invalid_request("volume_index must be a number")
    if store["status"] != "PROPOSED":
        raise ApiError("ERR_STORE_PRECONDITION",
                       "volume_index editable only while the store is PROPOSED")
    store["volume_index"] = vi
    touch(store)
    return success(pub(store), 200)


@bp.post("/rollouts/stores/<sid>/select-format")
def select_format_route(sid):
    require_roles(*REM)
    store = get_store(sid)
    body = get_body()
    body_rollout(body, expected_pid=store["rollout_program_id"])
    if "expected_store_version" not in body or body["expected_store_version"] is None:
        raise err_invalid_request("expected_store_version is required")
    expected = body["expected_store_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_store_version must be an integer")
    if store["status"] != "PROPOSED":
        raise ApiError("ERR_STORE_PRECONDITION",
                       "format selection requires a PROPOSED store")
    for ag in DB.agreements.values():
        if ag["store_id"] == sid and ag["status"] in ("ACTIVE", "EXECUTED"):
            raise ApiError("ERR_STORE_PRECONDITION",
                           "store has an ACTIVE or EXECUTED agreement")
    if expected != store["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_store_version mismatch")
    ta = DB.trade_areas[store["trade_area_id"]]
    fmt, proj = select_format(ta)
    if fmt is None:
        raise ApiError("ERR_NO_FEASIBLE_FORMAT",
                       "no format meets its minimum-revenue bar")
    store["format_type"] = fmt
    store["projected_revenue_cents"] = proj
    store["weekly_case_volume_base"] = WEEKLY_CASES[fmt]
    store["build_cost_cents"] = BUILD_COST[fmt]
    touch(store)
    ta["projected_revenue_cents"] = proj
    touch(ta)
    return success(pub(store), 200)


@bp.post("/rollouts/stores/<sid>/kill")
def kill_store(sid):
    require_roles(*REM)
    store = get_store(sid)
    body = get_body()
    program = body_rollout(body, expected_pid=store["rollout_program_id"])
    if store["status"] not in ("PROPOSED", "SITE_CONTROL", "UNDER_CONSTRUCTION"):
        raise ApiError("ERR_INVALID_STATE",
                       "only PROPOSED, SITE_CONTROL or UNDER_CONSTRUCTION stores may be killed")
    open_ag = _open_agreement_for_store(sid)
    if open_ag is not None:
        raise ApiError("ERR_SITE_CONTROL_ACTIVE",
                       "an agreement is still open for this store")
    was_under_construction = store["status"] == "UNDER_CONSTRUCTION"
    store["status"] = "KILLED"
    touch(store)
    for a in DB.dc_assignments.values():
        if a["store_id"] == sid and a["status"] == "ACTIVE":
            a["status"] = "SUPERSEDED"
            touch(a)
            dc = DB.dcs.get(a["distribution_center_id"])
            if dc is not None:
                dc["assigned_store_count"] -= 1
                dc["remaining_capacity"] = dc["store_capacity"] - dc["assigned_store_count"]
                touch(dc)
    for rp in DB.route_plans.values():
        if rp["store_id"] == sid and rp["status"] == "ACTIVE":
            rp["status"] = "SUPERSEDED"
            touch(rp)
    for op in DB.opening_plans.values():
        if op["store_id"] == sid and op["status"] in ("PLANNED", "LOCKED"):
            op["status"] = "CANCELLED"
            touch(op)
    recompute_capital(program)
    touch(program)
    return success(pub(store), 200)


@bp.post("/rollouts/stores/<sid>/record-sales")
def record_sales(sid):
    require_roles(*FA)
    store = get_store(sid)
    body = get_body()
    body_rollout(body, expected_pid=store["rollout_program_id"])
    if "open_year_sales_cents" not in body or body["open_year_sales_cents"] is None:
        raise err_invalid_request("open_year_sales_cents is required")
    sales = opt_int(body, "open_year_sales_cents")
    if store["status"] != "EXISTING":
        raise ApiError("ERR_INVALID_STATE",
                       "open_year_sales_cents may be recorded only on EXISTING stores")
    store["open_year_sales_cents"] = sales
    touch(store)
    return success(pub(store), 200)


# ---- developers ----------------------------------------------------------------

@bp.post("/rollouts/developers")
def create_developer():
    require_roles(*ADMIN)
    body = get_body()
    program = body_rollout(body)
    name = req_str(body, "name")
    check_name_unique(DB.developers, program["id"], name, "developer")
    d = base_entity()
    d.update({
        "rollout_program_id": program["id"],
        "name": name,
        "active_agreement_count": 0,
    })
    DB.developers[d["id"]] = d
    return success(pub(d), 201)


@bp.get("/rollouts/developers")
def list_developers():
    require_roles(*ALL)
    items = list(DB.developers.values())
    pid = request.args.get("rollout_program_id")
    if pid is not None:
        items = [d for d in items if d["rollout_program_id"] == pid]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(request.args)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/developers/<devid>")
def get_developer_by_id(devid):
    require_roles(*ALL)
    from helpers import get_developer
    return success(pub(get_developer(devid)), 200)


# ---- site control agreements ----------------------------------------------------

@bp.post("/rollouts/site-agreements")
def create_agreement():
    require_roles(*REM)
    body = get_body()
    program = body_rollout(body)
    store_id = body.get("store_id")
    if not isinstance(store_id, str):
        raise err_invalid_request("store_id is required")
    developer_id = body.get("developer_id")
    if not isinstance(developer_id, str):
        raise err_invalid_request("developer_id is required")
    if "committed_delivery_date" not in body or body["committed_delivery_date"] is None:
        raise err_invalid_request("committed_delivery_date is required")
    cdd_raw = body["committed_delivery_date"]
    cdd = parse_dt_field(cdd_raw, "committed_delivery_date")
    if "base_price_cents" not in body or body["base_price_cents"] is None:
        raise err_invalid_request("base_price_cents is required")
    base_price = opt_int(body, "base_price_cents")
    if "earnest_money_cents" not in body or body["earnest_money_cents"] is None:
        raise err_invalid_request("earnest_money_cents is required")
    earnest = opt_int(body, "earnest_money_cents")

    if base_price <= 0:
        raise err_validation("base_price_cents must be > 0")
    if earnest <= 0 or earnest >= base_price:
        raise err_validation("earnest_money_cents must be > 0 and < base_price_cents")

    store = DB.stores.get(store_id)
    if store is None or store["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "store not found in program")
    dev = DB.developers.get(developer_id)
    if dev is None or dev["rollout_program_id"] != program["id"]:
        raise ApiError("ERR_BAD_REFERENCE", "developer not found in program")

    # PRD §2.11 priority order: singleton rules (9) precede store-level
    # preconditions (10), so the duplicate-open-agreement check fires first.
    if _open_agreement_for_store(store_id) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE",
                       "store already has an open agreement")
    if store["status"] != "PROPOSED":
        raise ApiError("ERR_STORE_PRECONDITION",
                       "agreements may be created only for PROPOSED stores")

    ag = base_entity()
    ag.update({
        "rollout_program_id": program["id"],
        "store_id": store_id,
        "developer_id": developer_id,
        "committed_delivery_date": fmt_dt(cdd),
        "base_price_cents": base_price,
        "earnest_money_cents": earnest,
        "status": "DRAFT",
        "late_days": 0,
        "penalty_cents": 0,
    })
    DB.agreements[ag["id"]] = ag
    return success(pub(ag), 201)


@bp.get("/rollouts/site-agreements")
def list_agreements():
    require_roles(*ALL)
    items = list(DB.agreements.values())
    q = request.args
    if q.get("developer_id") is not None:
        items = [a for a in items if a["developer_id"] == q["developer_id"]]
    if q.get("store_id") is not None:
        items = [a for a in items if a["store_id"] == q["store_id"]]
    if q.get("rollout_program_id") is not None:
        items = [a for a in items if a.get("rollout_program_id") == q["rollout_program_id"]]
    items = sorted_by_creation(items)
    limit, offset = parse_pagination(q)
    page, pg = paginate(items, limit, offset)
    return success(pub_list(page), 200, pg)


@bp.get("/rollouts/site-agreements/<agid>")
def get_agreement_by_id(agid):
    require_roles(*ALL)
    from helpers import get_agreement
    return success(pub(get_agreement(agid)), 200)


@bp.post("/rollouts/site-agreements/<agid>/execute")
def execute_agreement(agid):
    require_roles(*REM)
    from helpers import get_agreement
    ag = get_agreement(agid)
    body = get_body()
    body_rollout(body, expected_pid=ag["rollout_program_id"])
    if ag["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "agreement must be DRAFT to execute")
    store = DB.stores[ag["store_id"]]
    if store["status"] != "PROPOSED":
        raise ApiError("ERR_STORE_PRECONDITION", "store must be PROPOSED")
    if not (ag["earnest_money_cents"] > 0 and ag["earnest_money_cents"] < ag["base_price_cents"]):
        raise err_validation("earnest_money_cents must be > 0 and < base_price_cents")
    ag["status"] = "EXECUTED"
    touch(ag)
    store["status"] = "SITE_CONTROL"
    touch(store)
    return success(pub(ag), 200)


@bp.post("/rollouts/site-agreements/<agid>/activate")
def activate_agreement(agid):
    require_roles(*REM)
    from helpers import get_agreement
    ag = get_agreement(agid)
    body = get_body()
    program = body_rollout(body, expected_pid=ag["rollout_program_id"])
    if ag["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE", "agreement must be EXECUTED to activate")
    require_active(program)
    dev = DB.developers[ag["developer_id"]]
    if dev["active_agreement_count"] >= 3:
        raise ApiError("ERR_DEVELOPER_CAPACITY_EXCEEDED",
                       "developer already has 3 ACTIVE agreements")
    store = DB.stores[ag["store_id"]]
    ag["status"] = "ACTIVE"
    touch(ag)
    dev["active_agreement_count"] += 1
    touch(dev)
    store["status"] = "UNDER_CONSTRUCTION"
    touch(store)
    recompute_capital(program)
    touch(program)
    return success(pub(ag), 200)


@bp.post("/rollouts/site-agreements/<agid>/deliveries")
def record_delivery(agid):
    require_roles(*REM)
    from helpers import get_agreement
    ag = get_agreement(agid)
    body = get_body()
    body_rollout(body, expected_pid=ag["rollout_program_id"])
    if "actual_delivery_date" not in body or body["actual_delivery_date"] is None:
        raise err_invalid_request("actual_delivery_date is required")
    actual = parse_dt_field(body["actual_delivery_date"], "actual_delivery_date")
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "agreement must be ACTIVE to record delivery")
    committed = parse_dt_field(ag["committed_delivery_date"], "committed_delivery_date")
    late_days, penalty = compute_penalty(committed, actual)
    ag["late_days"] = late_days
    ag["penalty_cents"] = penalty
    ag["status"] = "DELIVERED"
    touch(ag)
    dev = DB.developers[ag["developer_id"]]
    dev["active_agreement_count"] -= 1
    touch(dev)
    store = DB.stores[ag["store_id"]]
    store["status"] = "DELIVERED"
    touch(store)
    if late_days >= 30:
        for op in DB.opening_plans.values():
            if op["store_id"] == store["id"] and op["status"] in ("PLANNED", "LOCKED"):
                op["status"] = "CANCELLED"
                touch(op)
    program = DB.rollouts[ag["rollout_program_id"]]
    recompute_capital(program)
    touch(program)
    return success(pub(ag), 200)


@bp.post("/rollouts/site-agreements/<agid>/terminate")
def terminate_agreement(agid):
    require_roles(*REM)
    from helpers import get_agreement
    ag = get_agreement(agid)
    body = get_body()
    program = body_rollout(body, expected_pid=ag["rollout_program_id"])
    if ag["status"] not in ("DRAFT", "EXECUTED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE",
                       "only DRAFT, EXECUTED or ACTIVE agreements may be terminated")
    prev = ag["status"]
    ag["status"] = "TERMINATED"
    touch(ag)
    store = DB.stores[ag["store_id"]]
    if prev in ("EXECUTED", "ACTIVE"):
        store["status"] = "PROPOSED"
        touch(store)
    if prev == "ACTIVE":
        dev = DB.developers[ag["developer_id"]]
        dev["active_agreement_count"] -= 1
        touch(dev)
    recompute_capital(program)
    touch(program)
    return success(pub(ag), 200)
