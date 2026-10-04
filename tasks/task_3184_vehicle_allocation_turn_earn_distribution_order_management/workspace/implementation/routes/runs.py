"""Allocation runs and dealer allocations (PRD §3.3, §3.4, §3.5, §3.11)."""
from flask import Blueprint, request

import errors as err
from db import get_store, now_iso
from middleware import auth_context
from response import success_list, success_object
from services.core import (lock_recompute, publish_recompute)
from util import bump, new_entity, parse_dt, req_int, req_str, req_ts

bp = Blueprint("runs", __name__)

ALLOC_ONLY = ["RegionalAllocator"]
READ = ["RegionalAllocator", "Dealer", "ProductionScheduler"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _create_children(run: dict) -> None:
    """One OPEN DealerAllocation per ACTIVE dealer in ACTIVE regions (§3.3)."""
    regions = get_store("regions")
    for dealer in get_store("dealers").values():
        region = regions.get(dealer["region_id"])
        if dealer["status"] != "ACTIVE" or region is None or region["status"] != "ACTIVE":
            continue
        da = new_entity({
            "run_id": run["id"],
            "dealer_id": dealer["id"],
            "base_units": 0,
            "adjustment_units": 0,
            "final_units": 0,
            "consumed_units": 0,
            "retail_reserved_units": 0,
            "retail_consumed_units": 0,
            "status": "OPEN",
        })
        get_store("dealer_allocations")[da["id"]] = da


@bp.post("/wholesale/allocation-runs")
def create_run():
    auth_context(ALLOC_ONLY)
    body = _body()
    period = req_str(body, "period")
    model_line_id = req_str(body, "model_line_id")
    base_units = req_int(body, "base_units", 0)
    lookback_start = req_ts(body, "lookback_start")
    lookback_end = req_ts(body, "lookback_end")
    retail_priority_pct = req_int(body, "retail_priority_pct", 0, 100)

    if model_line_id not in get_store("model_lines"):
        raise err.not_found("model line not found")
    if parse_dt(lookback_end) <= parse_dt(lookback_start):
        raise err.validation("lookback_end must be strictly after lookback_start")
    for run in get_store("allocation_runs").values():
        if run["model_line_id"] == model_line_id and run["period"] == period:
            raise err.duplicate("period already used for this line")

    # Supersede an existing PUBLISHED run for the same line (§3.3).
    for existing in get_store("allocation_runs").values():
        if existing["model_line_id"] == model_line_id and existing["status"] == "PUBLISHED":
            existing["status"] = "SUPERSEDED"
            bump(existing)
            for da in get_store("dealer_allocations").values():
                if da["run_id"] == existing["id"] and da["status"] == "OPEN":
                    da["status"] = "LOCKED"
                    bump(da)

    run = new_entity({
        "period": period,
        "model_line_id": model_line_id,
        "base_units": base_units,
        "status": "DRAFT",
        "published_at": None,
        "lookback_start": lookback_start,
        "lookback_end": lookback_end,
        "retail_priority_pct": retail_priority_pct,
    })
    get_store("allocation_runs")[run["id"]] = run
    _create_children(run)
    return success_object(run, 201)


@bp.get("/wholesale/allocation-runs")
def list_runs():
    auth_context(READ)
    rows = list(get_store("allocation_runs").values())
    for key in ("model_line_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/allocation-runs/<rid>")
def get_run(rid):
    auth_context(READ)
    run = get_store("allocation_runs").get(rid)
    if run is None:
        raise err.not_found("run not found")
    return success_object(run)


@bp.post("/wholesale/allocation-runs/<rid>/publish")
def publish_run(rid):
    auth_context(ALLOC_ONLY)
    run = get_store("allocation_runs").get(rid)
    if run is None:
        raise err.not_found("run not found")
    if run["status"] != "DRAFT":
        raise err.invalid_state("run is not DRAFT")
    children = [da for da in get_store("dealer_allocations").values()
                if da["run_id"] == run["id"]]
    if not children:
        raise err.invalid_state("run has no DealerAllocation children")
    for other in get_store("allocation_runs").values():
        if (other["id"] != run["id"]
                and other["model_line_id"] == run["model_line_id"]
                and other["status"] == "PUBLISHED"):
            raise err.run_period_conflict()
    run["status"] = "PUBLISHED"
    run["published_at"] = now_iso()
    bump(run)
    publish_recompute(run)
    return success_object(run)


@bp.post("/wholesale/allocation-runs/<rid>/lock")
def lock_run(rid):
    auth_context(ALLOC_ONLY)
    run = get_store("allocation_runs").get(rid)
    if run is None:
        raise err.not_found("run not found")
    if run["status"] != "PUBLISHED":
        raise err.invalid_state("run is not PUBLISHED")
    children = [da for da in get_store("dealer_allocations").values()
                if da["run_id"] == run["id"]]
    if any(da["status"] != "LOCKED" for da in children):
        raise err.children_not_locked()
    for appeal in get_store("appeals").values():
        if appeal["run_id"] == run["id"] and appeal["state"] in ("FILED", "UNDER_REVIEW"):
            raise err.appeals_open()
    run["status"] = "LOCKED"
    bump(run)
    lock_recompute(run)
    return success_object(run)


@bp.get("/wholesale/allocation-runs/<rid>/dealer-allocations")
def list_run_dealer_allocations(rid):
    auth_context(READ)
    run = get_store("allocation_runs").get(rid)
    if run is None:
        raise err.not_found("run not found")
    rows = [da for da in get_store("dealer_allocations").values()
            if da["run_id"] == rid]
    if request.args.get("dealer_id"):
        rows = [r for r in rows if r["dealer_id"] == request.args["dealer_id"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/dealer-allocations")
def list_dealer_allocations():
    auth_context(READ)
    rows = list(get_store("dealer_allocations").values())
    for key in ("dealer_id", "run_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/dealer-allocations/<daid>")
def get_dealer_allocation(daid):
    auth_context(READ)
    da = get_store("dealer_allocations").get(daid)
    if da is None:
        raise err.not_found("dealer allocation not found")
    return success_object(da)


@bp.post("/wholesale/allocation-runs/<rid>/dealer-allocations/<daid>/lock")
def lock_dealer_allocation(rid, daid):
    auth_context(ALLOC_ONLY)
    run = get_store("allocation_runs").get(rid)
    if run is None:
        raise err.not_found("run not found")
    da = get_store("dealer_allocations").get(daid)
    if da is None or da["run_id"] != rid:
        raise err.not_found("dealer allocation not found in run")
    if da["status"] != "OPEN":
        raise err.invalid_state("dealer allocation is not OPEN")
    if run["status"] != "PUBLISHED":
        raise err.parent_not_active("run is not PUBLISHED")
    da["status"] = "LOCKED"
    bump(da)
    return success_object(da)
