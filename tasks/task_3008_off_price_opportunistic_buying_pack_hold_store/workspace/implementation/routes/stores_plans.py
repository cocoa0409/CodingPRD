"""Stores and allocation plans (including cluster allocation execution)."""
import math
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db, now
from middleware import require
from response import success, success_list
from services.calc import (
    CLUSTERS, LIVE_SKU_STATUSES,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, check_unique, paginate, serialize, sorted_list, new_id, wall_now_iso,
)

bp = Blueprint("stores_plans", __name__)

STORE_ROLES = ("AllocationManager", "PlanningLead", "StoreOpsLead", "PricingAnalyst")
PLAN_ROLES = ("AllocationManager", "PlanningLead", "Buyer")


# ------------------------------------------------------------------- stores
@bp.post("/stores")
def create_store():
    require(("AllocationManager",))
    vals = validate_body(get_body(required=True), {
        "store_code": ("str", True),
        "cluster_code": ("enum", True, CLUSTERS),
        "zone_code": ("str", True),
        "storage_capacity_units": ("int", True),
        "clearance_outlet": ("bool", False),
    })
    require_range(vals["storage_capacity_units"], lo=0, lo_exclusive=True,
                  field="storage_capacity_units")
    if not any(z["zone_code"] == vals["zone_code"] for z in db["zones"].values()):
        raise err.not_found("zone_code does not reference an existing price zone")
    check_unique("stores", "store_code", vals["store_code"], "store_code already exists")
    store = new_common()
    store.update(vals)
    store["clearance_outlet"] = vals.get("clearance_outlet", False)
    db["stores"][store["id"]] = store
    return success(serialize("store", store), status=201)


@bp.get("/stores")
def list_stores():
    require(STORE_ROLES)
    filters = {"cluster_code": request.args.get("cluster_code"),
               "zone_code": request.args.get("zone_code")}
    page, limit, offset, total = paginate(list(db["stores"].values()), filters)
    return success_list([serialize("store", s) for s in page], limit, offset, total)


@bp.get("/stores/<sid>")
def get_store(sid):
    require(STORE_ROLES)
    return success(serialize("store", get_or_404("stores", sid)))


@bp.get("/stores/<sid>/store-skus")
def store_skus(sid):
    require(("StoreOpsLead", "AllocationManager", "PlanningLead"))
    get_or_404("stores", sid)
    skus = [s for s in db["store_skus"].values() if s["store_id"] == sid]
    page, limit, offset, total = paginate(skus, {"status": request.args.get("status")})
    return success_list([serialize("store_sku", s) for s in page], limit, offset, total)


@bp.get("/stores/<sid>/shrink-cases")
def store_shrink_cases(sid):
    require(("ShrinkAuditor", "PlanningLead", "StoreOpsLead"))
    get_or_404("stores", sid)
    page, limit, offset, total = paginate(find_by("shrink_cases", "store_id", sid))
    return success_list([serialize("shrink_case", c) for c in page], limit, offset, total)


@bp.get("/stores/<sid>/liquidation-orders")
def store_liquidation_orders(sid):
    require(("PlanningLead", "StoreOpsLead"))
    get_or_404("stores", sid)
    page, limit, offset, total = paginate(find_by("liquidation_orders", "store_id", sid))
    return success_list([serialize("liquidation_order", o) for o in page], limit, offset, total)


# ------------------------------------------------------------------- allocation plans
@bp.post("/allocation-plans")
def create_plan():
    require(("AllocationManager",))
    vals = validate_body(get_body(required=True), {
        "lot_id": ("str", True),
        "season_id": ("str", True),
        "total_units": ("int", True),
        "cluster_weights": ("object", True),
        "expected_lot_version": ("int", True),
    })
    lot = get_or_404("lots", vals["lot_id"], "lot not found")
    get_or_404("seasons", vals["season_id"], "season not found")
    require_range(vals["total_units"], lo=0, lo_exclusive=True, field="total_units")
    weights = vals["cluster_weights"]
    for key, weight in weights.items():
        if key not in CLUSTERS:
            raise err.invalid_request(f"unknown cluster_code: {key}")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise err.invalid_request("cluster weights must be positive numbers")
    if lot["status"] != "ACCEPTED":
        raise err.invalid_state("allocation plans require an ACCEPTED lot")
    if vals["expected_lot_version"] != lot["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_lot_version does not match the lot version")
    plan = new_common()
    plan.update({
        "lot_id": lot["id"],
        "season_id": vals["season_id"],
        "total_units": vals["total_units"],
        "cluster_weights": {k: float(v) for k, v in weights.items()},
        "status": "DRAFT",
        "superseded_by_id": None,
    })
    db["plans"][plan["id"]] = plan
    touch(lot)
    return success(serialize("plan", plan), status=201)


@bp.get("/allocation-plans")
def list_plans():
    require(PLAN_ROLES)
    filters = {k: request.args.get(k)
               for k in ("lot_id", "season_id", "status", "superseded_by_id")}
    page, limit, offset, total = paginate(list(db["plans"].values()), filters)
    return success_list([serialize("plan", p) for p in page], limit, offset, total)


@bp.get("/allocation-plans/<pid>")
def get_plan(pid):
    require(PLAN_ROLES)
    return success(serialize("plan", get_or_404("plans", pid)))


@bp.post("/allocation-plans/<pid>/approve")
def approve_plan(pid):
    require(("AllocationManager",))
    plan = get_or_404("plans", pid)
    get_body()
    if plan["status"] != "DRAFT":
        raise err.invalid_state("only a DRAFT plan can be approved")
    present_clusters = {s["cluster_code"] for s in db["stores"].values()}
    weight_clusters = set(plan["cluster_weights"])
    if weight_clusters != present_clusters or \
            any(c not in present_clusters for c in weight_clusters):
        raise ApiError("ERR_CLUSTER_UNCOVERED",
                       "cluster_weights must cover exactly the clusters that have stores")
    for other in db["plans"].values():
        if other["id"] != plan["id"] and other["lot_id"] == plan["lot_id"] \
                and other["status"] in ("APPROVED", "EXECUTED"):
            raise ApiError("ERR_LOT_ALREADY_ALLOCATED",
                           "another plan for this lot is APPROVED or EXECUTED")
    for other in db["plans"].values():
        if other["id"] != plan["id"] and other["lot_id"] == plan["lot_id"] \
                and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = plan["id"]
            touch(other)
    plan["status"] = "APPROVED"
    touch(plan)
    return success(serialize("plan", plan))


@bp.post("/allocation-plans/<pid>/execute")
def execute_plan(pid):
    require(("AllocationManager",))
    plan = get_or_404("plans", pid)
    get_body()
    if plan["status"] != "APPROVED":
        raise err.invalid_state("only an APPROVED plan can be executed")
    season = db["seasons"].get(plan["season_id"])
    if season is None or season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", "the plan's selling season is not OPEN")
    lot = db["lots"].get(plan["lot_id"])
    lot_lines = sorted_list(find_by("lot_lines", "lot_id", plan["lot_id"]))

    # ---------------- cluster allocation (steps 1-3) ----------------
    weights = plan["cluster_weights"]
    total_units = plan["total_units"]
    eligible = [s for s in db["stores"].values()
                if s["cluster_code"] in weights and s["storage_capacity_units"] > 0]
    by_cluster = {}
    for store in sorted_list(eligible):
        by_cluster.setdefault(store["cluster_code"], []).append(store)
    # capacity already consumed by live/on-hand placements
    used = {}
    for sku in db["store_skus"].values():
        if sku["status"] in LIVE_SKU_STATUSES:
            used[sku["store_id"]] = used.get(sku["store_id"], 0) + sku["units_on_hand"]

    weight_sum = sum(weights.values())
    quotas = {}
    fractions = []
    for cluster, weight in weights.items():
        exact = total_units * weight / weight_sum
        quotas[cluster] = math.floor(exact)
        fractions.append((-(exact - math.floor(exact)), cluster))
    remainder = total_units - sum(quotas.values())
    for _, cluster in sorted(fractions):
        if remainder <= 0:
            break
        quotas[cluster] += 1
        remainder -= 1

    def capacity_of(store):
        return max(0, store["storage_capacity_units"] - used.get(store["id"], 0))

    allocation = {}
    leftover = 0
    for cluster, quota in quotas.items():
        stores = by_cluster.get(cluster, [])
        if not stores:
            leftover += quota
            continue
        n = len(stores)
        base = quota // n
        rem = quota - base * n
        # Base share first, capped by capacity; the cluster remainder is then
        # dealt one unit per store in created_at order, still capped.
        for store in stores:
            give = min(base, capacity_of(store))
            allocation[store["id"]] = allocation.get(store["id"], 0) + give
            used[store["id"]] = used.get(store["id"], 0) + give
            leftover += base - give
        for store in stores:
            if rem <= 0:
                break
            if capacity_of(store) > 0:
                allocation[store["id"]] += 1
                used[store["id"]] += 1
                rem -= 1
        leftover += rem
        # overflow to the next stores in the cluster in created_at order
        for store in stores:
            if leftover <= 0:
                break
            room = capacity_of(store)
            if room <= 0:
                continue
            give = min(room, leftover)
            allocation[store["id"]] = allocation.get(store["id"], 0) + give
            used[store["id"]] += give
            leftover -= give
    # spill to other clusters by descending weight (tie: cluster_code ASC)
    cluster_order = sorted(weights, key=lambda c: (-weights[c], c))
    while leftover > 0:
        progressed = False
        for cluster in cluster_order:
            for store in by_cluster.get(cluster, []):
                if leftover <= 0:
                    break
                room = capacity_of(store)
                if room > 0:
                    give = min(room, leftover)
                    allocation[store["id"]] = allocation.get(store["id"], 0) + give
                    used[store["id"]] += give
                    leftover -= give
                    progressed = True
        if not progressed:
            raise ApiError("ERR_STORE_OVER_CAPACITY",
                           "allocation exceeds the storage capacity of eligible stores")

    # ---------------- tickets & placement ----------------
    stores_by_id = {s["id"]: s for s in eligible}
    for store_id, units in allocation.items():
        if units <= 0:
            continue
        store = stores_by_id[store_id]
        for line in lot_lines:
            ticket = next((t for t in db["tickets"].values()
                           if t["lot_line_id"] == line["id"]
                           and t["zone_code"] == store["zone_code"]
                           and t["status"] == "ACTIVE"), None)
            if ticket is None:
                raise ApiError("ERR_TICKET_NOT_ISSUED",
                               "every placed lot line needs an ACTIVE ticket for the store's zone")
    for store_id, units in allocation.items():
        if units <= 0:
            continue
        store = stores_by_id[store_id]
        for line in lot_lines:
            ticket = next(t for t in db["tickets"].values()
                          if t["lot_line_id"] == line["id"]
                          and t["zone_code"] == store["zone_code"]
                          and t["status"] == "ACTIVE")
            sku = new_common()
            sku.update({
                "store_id": store_id,
                "lot_line_id": line["id"],
                "ticket_id": ticket["id"],
                "season_id": plan["season_id"],
                "allocation_plan_id": plan["id"],
                "units_on_hand": units,
                "floor_date": now(),
                "weeks_on_floor": 0,
                "markdown_step": 0,
                "current_price_cents": ticket["ticket_retail_cents"],
                "status": "ON_FLOOR",
            })
            db["store_skus"][sku["id"]] = sku
    plan["status"] = "EXECUTED"
    touch(plan)
    return success(serialize("plan", plan))


@bp.post("/allocation-plans/<pid>/cancel")
def cancel_plan(pid):
    require(("AllocationManager",))
    plan = get_or_404("plans", pid)
    get_body()
    if plan["status"] not in ("DRAFT", "APPROVED"):
        raise err.invalid_state("only a DRAFT or APPROVED plan can be cancelled")
    plan["status"] = "CANCELLED"
    touch(plan)
    return success(serialize("plan", plan))


@bp.get("/allocation-plans/<pid>/store-skus")
def plan_store_skus(pid):
    require(("AllocationManager", "PlanningLead", "StoreOpsLead"))
    get_or_404("plans", pid)
    page, limit, offset, total = paginate(find_by("store_skus", "allocation_plan_id", pid))
    return success_list([serialize("store_sku", s) for s in page], limit, offset, total)
