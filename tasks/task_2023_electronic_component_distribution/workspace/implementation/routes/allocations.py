"""AllocationRun endpoints: fair-share computation and publication."""

from flask import Blueprint, request

import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    available_supply,
    get_allocation_run_or_404,
    get_json_body,
    get_part_or_404,
    mint_id,
    paginate,
    pagination_params,
    recompute_order_totals,
    recompute_part_availability,
    reserve_lots_fefo,
    serialize_run,
    stamp_now,
)

bp = Blueprint("allocations", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def _eligible_lines(part_id):
    lines = []
    for line in db.order_lines.values():
        if line["part_id"] != part_id or line["status"] != "OPEN":
            continue
        order = db.orders.get(line["order_id"])
        if order is not None and order["status"] == "ACKNOWLEDGED":
            lines.append(line)
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


def _fair_share(part, lines, supply):
    """Compute per-line allocations per the fair_share_allocation calculation."""
    mline = db.manufacturer_lines.get(part["manufacturer_line_id"])
    basis = mline["allocation_policy"] if mline else "BACKLOG_BASIS"
    demand = sum(l["quantity"] for l in lines)
    result = {}
    if supply >= demand:
        for l in lines:
            result[l["id"]] = l["quantity"]
        return result

    weights = {}
    for l in lines:
        if basis == "USAGE_BASIS":
            customer = db.customers.get(
                db.orders[l["order_id"]]["customer_id"] if l["order_id"] in db.orders else None
            )
            weights[l["id"]] = customer["trailing_12mo_component_usage_units"] if customer else 0
        else:
            weights[l["id"]] = l["quantity"]
    W = sum(weights.values())
    alloc = {}
    for l in lines:
        w = weights[l["id"]]
        raw = (supply * w) // W if W > 0 else 0
        alloc[l["id"]] = min(l["quantity"], raw)
    remainder = supply - sum(alloc.values())
    # one unit per pass over lines below quantity, ordered by creation time
    # (line creation order via _seq captures the PRD's "line creation time"
    # ordering at a granularity finer than the logical-clock timestamp, which
    # ties across lines created within the same instant), then ship_date, then
    # quantity DESC.
    order_keys = sorted(lines, key=lambda l: (l["_seq"], l["_ship_date"], -l["quantity"]))
    while remainder > 0:
        progressed = False
        for l in order_keys:
            if remainder <= 0:
                break
            if alloc[l["id"]] < l["quantity"]:
                alloc[l["id"]] += 1
                remainder -= 1
                progressed = True
        if not progressed:
            break
    return alloc


@bp.post("/allocation-runs")
def create_allocation_run():
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    body = get_json_body()
    part_id = body.get("part_id")
    if not isinstance(part_id, str) or part_id == "":
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "part_id is required.")
    if "expected_part_version" not in body or body["expected_part_version"] is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "expected_part_version is required.")
    expected = body["expected_part_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "expected_part_version must be an integer.")

    part = get_part_or_404(part_id)
    if expected != part["version"]:
        raise ApiError(E.ERR_STALE_PART_VERSION, 412, "Stale part version.")

    supply = available_supply(part_id)
    lines = _eligible_lines(part_id)
    demand = sum(l["quantity"] for l in lines)
    if supply == 0:
        raise ApiError(E.ERR_NO_ALLOCATABLE_SUPPLY, 409, "No allocatable supply.")
    if demand == 0:
        raise ApiError(E.ERR_NO_OPEN_DEMAND, 409, "No open demand.")

    # supersede the prior PROVISIONAL run for this part
    for run in db.allocation_runs.values():
        if run["part_id"] == part_id and run["status"] == "PROVISIONAL":
            run["status"] = "SUPERSEDED"
            run["updated_at"] = stamp_now()
            run["version"] += 1

    alloc = _fair_share(part, lines, supply)
    run_lines = [{"order_line_id": l["id"], "allocated_qty": alloc[l["id"]]} for l in lines]

    mline = db.manufacturer_lines.get(part["manufacturer_line_id"])
    now = stamp_now()
    run = {
        "id": mint_id(),
        "part_id": part_id,
        "basis": mline["allocation_policy"] if mline else "BACKLOG_BASIS",
        "total_supply_qty": supply,
        "total_demand_qty": demand,
        "lines": run_lines,
        "status": "PROVISIONAL",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.allocation_runs[run["id"]] = run

    part["version"] += 1
    part["updated_at"] = now
    return success(serialize_run(run), status=201)


@bp.get("/allocation-runs")
def list_allocation_runs():
    require_auth()
    limit, offset = pagination_params()
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    items = list(db.allocation_runs.values())
    if part_id is not None:
        items = [r for r in items if r["part_id"] == part_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_run(r) for r in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/allocation-runs/<runId>")
def get_allocation_run(runId):
    require_auth()
    run = get_allocation_run_or_404(runId)
    return success(serialize_run(run), status=200)


@bp.post("/allocation-runs/<runId>/publish")
def publish_allocation_run(runId):
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    run = get_allocation_run_or_404(runId)
    if run["status"] != "PROVISIONAL":
        raise ApiError(
            E.ERR_ALLOCATION_RUN_NOT_PROVISIONAL, 409, "Allocation run is not PROVISIONAL."
        )
    part_id = run["part_id"]
    total_alloc = sum(x["allocated_qty"] for x in run["lines"])
    if available_supply(part_id) < total_alloc:
        raise ApiError(
            E.ERR_QUANTITY_EXCEEDS_AVAILABLE,
            409,
            "Current supply no longer covers the run's total allocation.",
        )

    touched_orders = []
    for x in run["lines"]:
        line = db.order_lines.get(x["order_line_id"])
        if line is None:
            continue
        if line["status"] == "OPEN":
            line["allocated_qty"] = x["allocated_qty"]
            line["status"] = "ALLOCATED"
            line["updated_at"] = stamp_now()
            line["version"] += 1
            if line["order_id"] not in touched_orders:
                touched_orders.append(line["order_id"])

    reserve_lots_fefo(part_id, total_alloc)

    for oid in touched_orders:
        order = db.orders.get(oid)
        if order is not None:
            recompute_order_totals(order, bump=True)

    run["status"] = "PUBLISHED"
    run["updated_at"] = stamp_now()
    run["version"] += 1

    recompute_part_availability(part_id)
    part = db.parts.get(part_id)
    if part is not None:
        part["version"] += 1
        part["updated_at"] = stamp_now()
    return success(serialize_run(run), status=200)
