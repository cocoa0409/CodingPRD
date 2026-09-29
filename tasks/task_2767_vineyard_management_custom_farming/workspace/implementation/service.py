"""Cross-cutting route helpers: list plumbing, ladder rungs 9-20 primitives,
cascades and the settlement statement.
"""

from datetime import timedelta
from decimal import Decimal

from flask import request

import calc
import derive
import store
from common import ApiError, D, ZERO, invalid, r2
from validate import pagination, paginate

# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------


def filtered(table, specs):
    """specs: iterable of (query_param, row_key) pairs, compared as strings."""
    rows = list(table.values())
    for param, key in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        wanted = raw
        kept = []
        for row in rows:
            value = row.get(key)
            if value is None:
                continue
            if str(value) == wanted:
                kept.append(row)
        rows = kept
    return rows


def page_rows(rows, serializer, limit, offset, key=None, reverse=False):
    if key is None:
        key = store.created_key
    rows = sorted(rows, key=key, reverse=reverse)
    window, total = paginate(rows, limit, offset)
    return [serializer(row) for row in window], limit, offset, total


def page(rows, serializer, key=None, reverse=False):
    """Pagination bounds (rung 8) are read here; safe only when the endpoint
    carries no path id whose existence must be checked afterwards."""
    limit, offset = pagination()
    return page_rows(rows, serializer, limit, offset, key=key, reverse=reverse)


# --------------------------------------------------------------------------
# Rung 9 / 10 — existence
# --------------------------------------------------------------------------


def get_vineyard(row_id):
    return store.find(store.vineyards, row_id, "ERR_VINEYARD_NOT_FOUND")


def get_block(row_id):
    return store.find(store.blocks, row_id, "ERR_BLOCK_NOT_FOUND")


def get_contract(row_id):
    return store.find(store.contracts, row_id, "ERR_CONTRACT_NOT_FOUND")


def get_plan(row_id):
    return store.find(store.plans, row_id, "ERR_PLAN_NOT_FOUND")


def get_crew(row_id):
    return store.find(store.crews, row_id, "ERR_CREW_NOT_FOUND")


def get_work_order(row_id):
    return store.find(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")


def get_spray(row_id):
    return store.find(store.spray_records, row_id, "ERR_SPRAY_NOT_FOUND")


def get_irrigation(row_id):
    return store.find(store.irrigation_events, row_id, "ERR_IRRIGATION_EVENT_NOT_FOUND")


def get_window(row_id):
    return store.find(store.delivery_windows, row_id, "ERR_DELIVERY_WINDOW_NOT_FOUND")


def get_load(row_id):
    return store.find(store.harvest_loads, row_id, "ERR_HARVEST_LOAD_NOT_FOUND")


def get_observation(row_id):
    return store.find(store.pest_observations, row_id, "ERR_PEST_OBSERVATION_NOT_FOUND")


# --------------------------------------------------------------------------
# Rung 11 / 12 — ownership
# --------------------------------------------------------------------------


def require_vineyard_owner(role, user_id, vineyard_id):
    if role == "ClientOwner" and user_id != vineyard_id:
        raise ApiError("ERR_VINEYARD_OWNERSHIP_REQUIRED", 403)


def require_crew_owner(role, user_id, crew_id):
    if role == "CrewSupervisor" and user_id != crew_id:
        raise ApiError("ERR_CREW_OWNERSHIP_REQUIRED", 403)


# --------------------------------------------------------------------------
# Rung 15 — state helpers
# --------------------------------------------------------------------------


def require_block_live(block):
    if block["farming_status"] == "REMOVED":
        raise ApiError("ERR_BLOCK_REMOVED", 409)


def require_plan_approved(plan):
    if plan["plan_status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409)


def require_crew_active(crew):
    if crew["crew_status"] != "ACTIVE":
        raise ApiError("ERR_CREW_INACTIVE", 409)


def require_state(actual, expected, error_id):
    if actual != expected:
        raise ApiError(error_id, 409)


# --------------------------------------------------------------------------
# Rung 16 — segregation of duties
# --------------------------------------------------------------------------


def require_distinct(user_id, others):
    for other in others:
        if other is not None and user_id == other:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)


# --------------------------------------------------------------------------
# Rung 18 — crew double booking
# --------------------------------------------------------------------------

TRAVEL_GAP = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)
NO_GAP = timedelta(0)


def crew_conflicts(crew_id, block_id, start, end):
    for order in store.work_orders.values():
        if order["crew_id"] != crew_id:
            continue
        if order["execution_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        gap = NO_GAP if order["block_id"] == block_id else TRAVEL_GAP
        if start < order["_end"] + gap and order["_start"] < end + gap:
            return True
    return False


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------


def cascade_spray_applied(spray, block):
    """Depth-5 cascade of POST /spray-records/{id}/apply."""
    store.touch(block)
    new_rei = derive.block_clearances(block)[0]
    if new_rei is None:
        return
    candidates = []
    for order in store.work_orders.values():
        if order["block_id"] != block["id"]:
            continue
        if order["execution_status"] != "SCHEDULED":
            continue
        if not (order["_start"] < new_rei):
            continue
        crew = store.crews.get(order["crew_id"])
        if crew is not None and crew["pest_certified"]:
            continue
        candidates.append(order)
    candidates.sort(key=lambda o: (o["_start"], o["created_at"], o["_seq"]))
    for order in candidates:
        order["execution_status"] = "CANCELLED"
        order["cancel_reason"] = "REENTRY_RESTRICTION"
        store.touch(order)


# --------------------------------------------------------------------------
# Settlement (PRD 3.9)
# --------------------------------------------------------------------------


def block_direct_cost(block, contract, total_acres):
    labor = ZERO
    for order in store.work_orders.values():
        if order["block_id"] == block["id"] and order["execution_status"] == "COMPLETED":
            if order["actual_labor_cost"] is not None:
                labor += order["actual_labor_cost"]
    materials = ZERO
    for spray in store.spray_records.values():
        if spray["block_id"] == block["id"] and spray["spray_status"] in ("APPLIED", "VERIFIED"):
            materials += spray["material_cost"]
    water = ZERO
    for event in store.irrigation_events.values():
        if event["block_id"] == block["id"] and event["irrigation_status"] == "APPLIED":
            if event["water_cost"] is not None:
                water += event["water_cost"]
    acres = block["contracted_acres"]
    if acres is None:
        acres = ZERO
    if total_acres == ZERO:
        overhead = ZERO
    else:
        overhead = contract["period_overhead_pool"] * acres / total_acres
    return r2(labor + materials + water + overhead)


def settlement_statement(contract, mode, period_end_date):
    blocks = sorted(derive.contract_blocks(contract["id"]), key=store.created_key)
    total_acres = ZERO
    for block in blocks:
        if block["contracted_acres"] is not None:
            total_acres += block["contracted_acres"]

    direct_cost_total = ZERO
    for block in blocks:
        direct_cost_total += block_direct_cost(block, contract, total_acres)

    fee_base = derive.management_fee_base(contract)
    share = Decimal("1") if mode == "FINAL" else calc.PROVISIONAL_PASS_THROUGH_SHARE
    pass_through = r2(direct_cost_total * contract["cost_pass_through_pct"] * share)
    tier_basis = r2(fee_base + pass_through)
    discount_pct = calc.volume_discount_pct(tier_basis)
    volume_discount = r2(fee_base * discount_pct)
    if mode == "FINAL":
        quality_incentive = derive.contract_aggregates(contract)["accrued_quality_incentive"]
    else:
        quality_incentive = Decimal("0.00")
    total_billable = r2(fee_base + pass_through - volume_discount + quality_incentive)

    contract["settled_period_count"] = contract["settled_period_count"] + 1
    contract["last_settlement_total"] = total_billable
    if mode == "FINAL" and period_end_date >= contract["period_end"]:
        contract["contract_status"] = "CLOSED"
    store.touch(contract)

    return {
        "direct_cost_total": direct_cost_total,
        "management_fee_base": fee_base,
        "pass_through": pass_through,
        "tier_basis": tier_basis,
        "volume_discount_pct": discount_pct,
        "volume_discount": volume_discount,
        "quality_incentive": quality_incentive,
        "total_billable": total_billable,
    }
