"""Supply plans and the rationing waterfall (PRD 3.5, 3.6)."""
from flask import Blueprint

from auth import (ROLE_CUSTOMER_REP, ROLE_DEMAND_PLANNER,
                  ROLE_DEMAND_REVIEW_LEAD, ROLE_EXECUTIVE_SPONSOR,
                  ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER, endpoint, find_or_404,
                  phase_gate, scope_list_customer, scope_row_customer)
from calcs import (calc_constrained_supply, calc_rationing_waterfall,
                   fill_rate, forecasts_of)
from cascades import allocations_of, recompute_cycle
from envelope import respond_list, respond_object
from errors import ApiError
from store import new_row, ordered, public, public_all, store, touch
from validators import (get_body, paginate, pagination, query_enum, query_str,
                        req_id)

bp = Blueprint("supply", __name__)

READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]
ALLOCATION_READ_ROLES = [ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                         ROLE_EXECUTIVE_SPONSOR, ROLE_CUSTOMER_REP]

PLAN_STATUSES = ("PLANNED", "RATIONED", "STALE", "COMMITTED")
CONSTRAINT_TYPES = ("NONE", "MATERIAL", "CAPACITY", "INVENTORY_TARGET")
ALLOCATION_STATUSES = ("ALLOCATED", "WITHHELD_CREDIT_HOLD", "VOIDED")


@bp.post("/sop/supply-plans")
@endpoint([ROLE_SUPPLY_PLANNER])
def create_supply_plan():
    body = get_body()
    cycle_id = req_id(body, "cycle_id")
    item_id = req_id(body, "item_id")

    cycle = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")
    item = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")

    phase_gate(cycle, "SUPPLY_REVIEW")

    # priority 130 -- the demand side must be settled
    lines = forecasts_of(cycle_id, item_id)
    if not lines or any(f["status"] not in ("CONSENSUS_LOCKED",
                                           "RUNOUT_TRUNCATED") for f in lines):
        raise ApiError("ERR_FORECAST_NOT_LOCKED",
                       "Every forecast line of this cycle and item must be "
                       "locked or truncated before a supply plan is built")

    # priority 150 -- at most one non-STALE plan per cycle-and-item pair
    for other in store.supply_plans.values():
        if (other["cycle_id"] == cycle_id and other["item_id"] == item_id
                and other["status"] != "STALE"):
            raise ApiError("ERR_SUPPLY_PLAN_EXISTS",
                           "A supply plan already exists for that cycle and item")

    family = store.families[item["family_id"]]
    derived = calc_constrained_supply(cycle, item, family)

    row = new_row()
    row.update({"cycle_id": cycle_id, "item_id": item_id})
    row.update(derived)
    row["status"] = "PLANNED"
    row["requires_replan"] = False
    store.supply_plans[row["id"]] = row

    recompute_cycle(cycle, bump=True)
    return respond_object(public(row), 201)


@bp.post("/sop/supply-plans/<supply_plan_id>/ration")
@endpoint([ROLE_SUPPLY_PLANNER])
def ration_supply_plan(supply_plan_id):
    get_body()
    plan = find_or_404("supply_plans", supply_plan_id, "ERR_SUPPLY_PLAN_NOT_FOUND")
    cycle = store.cycles.get(plan["cycle_id"])
    if cycle is not None:
        phase_gate(cycle, "SUPPLY_REVIEW")

    if plan["status"] != "PLANNED":
        raise ApiError("ERR_SUPPLY_PLAN_NOT_RATIONABLE",
                       "A supply plan in %s may not be rationed" % plan["status"])

    rows, remaining = calc_rationing_waterfall(plan)
    for customer, requested, allocated, status, pass_name in rows:
        allocation = new_row()
        allocation.update({
            "supply_plan_id": plan["id"],
            "customer_id": customer["id"],
            "requested_units": requested,
            "allocated_units": allocated,
            "fill_rate_pct": float(fill_rate(allocated, requested)),
            "allocation_status": status,
            "allocation_pass": pass_name,
        })
        store.allocations[allocation["id"]] = allocation

    plan["unallocated_units"] = remaining
    plan["status"] = "RATIONED"
    touch(plan)
    return respond_object(public(plan))


@bp.get("/sop/supply-plans/<supply_plan_id>")
@endpoint(READ_ROLES)
def get_supply_plan(supply_plan_id):
    row = find_or_404("supply_plans", supply_plan_id, "ERR_SUPPLY_PLAN_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/supply-plans")
@endpoint(READ_ROLES)
def list_supply_plans():
    limit, offset = pagination()
    cycle_id = query_str("cycle_id")
    item_id = query_str("item_id")
    status = query_enum("status", PLAN_STATUSES)
    constraint_type = query_enum("constraint_type", CONSTRAINT_TYPES)
    rows = ordered(store.supply_plans.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if item_id is not None:
        rows = [r for r in rows if r["item_id"] == item_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if constraint_type is not None:
        rows = [r for r in rows if r["constraint_type"] == constraint_type]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)


@bp.get("/sop/allocations/<allocation_id>")
@endpoint(ALLOCATION_READ_ROLES)
def get_allocation(allocation_id):
    row = find_or_404("allocations", allocation_id, "ERR_ALLOCATION_NOT_FOUND")
    scope_row_customer(row["customer_id"])
    return respond_object(public(row))


@bp.get("/sop/allocations")
@endpoint(ALLOCATION_READ_ROLES)
def list_allocations():
    limit, offset = pagination()
    scope_list_customer()
    supply_plan_id = query_str("supply_plan_id")
    customer_id = query_str("customer_id")
    allocation_status = query_enum("allocation_status", ALLOCATION_STATUSES)
    rows = ordered(store.allocations.values())
    if supply_plan_id is not None:
        rows = [r for r in rows if r["supply_plan_id"] == supply_plan_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if allocation_status is not None:
        rows = [r for r in rows if r["allocation_status"] == allocation_status]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
