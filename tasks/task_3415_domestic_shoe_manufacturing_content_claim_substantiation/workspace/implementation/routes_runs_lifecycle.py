"""ProductionRun lifecycle transitions (PRD 3.5): reserve-materials,
release-materials, start, hold, resume, complete, cancel.

Validation families are evaluated in the PRD 2.8 order: existence (incl. the
reserve-time allocation lookup) -> schema -> state -> temporal -> structural
-> fiscal.
"""
from flask import Blueprint

import calcs
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj
from state import DB, touch
from validation import body, req_int
from routes_runs import get_run, find_allocation

bp = Blueprint("runs_lifecycle", __name__)


def _factory_ownership_guard(run, role, uid):
    """Family 3 identity scoping: FactoryManager holds/resumes own factory only."""
    if role == "FactoryManager" and run["factory_id"] != uid:
        raise ApiError(
            "ERR_FACTORY_OWNERSHIP_MISMATCH",
            "a FactoryManager may hold/resume only runs of the factory whose id equals X-User-ID",
        )


@bp.post("/footwear/production-runs/<rid>/reserve-materials")
@require_roles("ProductionPlanner")
def reserve_materials(rid, _uid, _role):
    run = get_run(rid)
    # Family 4: the week's allocation must exist for (factory_id, iso_week).
    alloc = find_allocation(run["factory_id"], run["iso_week"])
    if alloc is None:
        raise ApiError(
            "ERR_ALLOCATION_NOT_FOUND",
            "no capacity allocation exists for the run's (factory_id, iso_week)",
        )
    # Family 6: state preconditions.
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "run must be PLANNED to reserve materials")
    model = DB["models"][run["model_id"]]
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_NOT_ACTIVE", "the run's model must be ACTIVE")
    factory = DB["factories"][run["factory_id"]]
    if factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_NOT_ACTIVE", "the run's factory must be ACTIVE")
    if alloc["status"] != "LOCKED":
        raise ApiError("ERR_ALLOCATION_NOT_LOCKED", "the week's allocation must be LOCKED")
    # Family 8: half-open line-window overlap; touching boundaries do not conflict.
    for other in DB["runs"].values():
        if other["id"] == run["id"]:
            continue
        if other["factory_id"] == run["factory_id"] \
                and other["line_index"] == run["line_index"] \
                and other["status"] in constants.LINE_HOLDING_STATES:
            if run["start_day"] < other["end_day"] and other["start_day"] < run["end_day"]:
                raise ApiError(
                    "ERR_LINE_WINDOW_CONFLICT",
                    "another active run overlaps this (factory, line_index) window",
                )
    # Family 9: FIFO material availability, atomic across all BOM lines.
    entries = calcs.fifo_allocate(run, model)
    # Family 11: the week's pool must cover consumed + this run (equality allowed).
    pool = alloc["domestic_reserved_units"] if factory["location_type"] == "DOMESTIC" \
        else alloc["import_reserved_units"]
    consumed = sum(
        o["planned_units"] for o in DB["runs"].values()
        if o["factory_id"] == run["factory_id"] and o["iso_week"] == run["iso_week"]
        and o["status"] in constants.CONSUMED_RUN_STATES
    )
    if consumed + run["planned_units"] > pool:
        raise ApiError(
            "ERR_CAPACITY_WEEK_EXCEEDED",
            "the week's remaining capacity pool cannot cover this run",
        )
    calcs.apply_consumption(entries)
    run["consumed_lots"] = entries
    run["status"] = "MATERIAL_RESERVED"
    touch(run)
    return ok_obj(serializers.pub(run))


@bp.post("/footwear/production-runs/<rid>/release-materials")
@require_roles("ProductionPlanner")
def release_materials(rid, _uid, _role):
    run = get_run(rid)
    if run["status"] != "MATERIAL_RESERVED":
        raise ApiError("ERR_INVALID_STATE", "run must be MATERIAL_RESERVED to release materials")
    calcs.release_consumption(run)
    run["status"] = "PLANNED"
    touch(run)
    return ok_obj(serializers.pub(run))


@bp.post("/footwear/production-runs/<rid>/start")
@require_roles("ProductionPlanner")
def start_run(rid, _uid, _role):
    run = get_run(rid)
    if run["status"] != "MATERIAL_RESERVED":
        raise ApiError("ERR_INVALID_STATE", "run must be MATERIAL_RESERVED to start")
    factory = DB["factories"][run["factory_id"]]
    if factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_NOT_ACTIVE", "the run's factory must be ACTIVE")
    if calcs.workforce_shortfall(run["factory_id"]):
        raise ApiError(
            "ERR_WORKFORCE_SHORTFALL",
            "fewer ACTIVE CERTIFIED workers than REQUIRED_WORKERS_PER_RUN for some operation",
        )
    for order in DB["orders"].values():
        if order["production_run_id"] == run["id"] \
                and order["production_status"] == "SCHEDULED":
            order["production_status"] = "IN_PRODUCTION"
            touch(order)
    run["status"] = "IN_PRODUCTION"
    touch(run)
    return ok_obj(serializers.pub(run))


@bp.post("/footwear/production-runs/<rid>/hold")
@require_roles("ProductionPlanner", "FactoryManager")
def hold_run(rid, _uid, _role):
    run = get_run(rid)
    _factory_ownership_guard(run, _role, _uid)
    if run["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "run must be IN_PRODUCTION to hold")
    run["status"] = "QUALITY_HOLD"
    touch(run)
    return ok_obj(serializers.pub(run))


@bp.post("/footwear/production-runs/<rid>/resume")
@require_roles("ProductionPlanner", "FactoryManager")
def resume_run(rid, _uid, _role):
    run = get_run(rid)
    _factory_ownership_guard(run, _role, _uid)
    if run["status"] != "QUALITY_HOLD":
        raise ApiError("ERR_INVALID_STATE", "run must be QUALITY_HOLD to resume")
    factory = DB["factories"][run["factory_id"]]
    if factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_NOT_ACTIVE", "the run's factory must be ACTIVE")
    if calcs.workforce_shortfall(run["factory_id"]):
        raise ApiError(
            "ERR_WORKFORCE_SHORTFALL",
            "fewer ACTIVE CERTIFIED workers than REQUIRED_WORKERS_PER_RUN for some operation",
        )
    run["status"] = "IN_PRODUCTION"
    touch(run)
    return ok_obj(serializers.pub(run))


@bp.post("/footwear/production-runs/<rid>/complete")
@require_roles("ProductionPlanner")
def complete_run(rid, _uid, _role):
    run = get_run(rid)
    # Family 5 (schema) precedes family 6 (state).
    b = body()
    smin = req_int(b, "actual_stitching_minutes", min_v=0)
    lmin = req_int(b, "actual_lasting_minutes", min_v=0)
    amin = req_int(b, "actual_assembly_minutes", min_v=0)
    if run["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "run must be IN_PRODUCTION to complete")
    run["actual_stitching_minutes"] = smin
    run["actual_lasting_minutes"] = lmin
    run["actual_assembly_minutes"] = amin
    run["certified_unit_cost_cents"] = calcs.run_unit_cost(run)
    run["status"] = "COMPLETED"
    touch(run)
    return ok_obj(serializers.pub(run))


@bp.post("/footwear/production-runs/<rid>/cancel")
@require_roles("ProductionPlanner")
def cancel_run(rid, _uid, _role):
    run = get_run(rid)
    if run["status"] == "PLANNED":
        run["status"] = "CANCELLED"
        touch(run)
    elif run["status"] == "MATERIAL_RESERVED":
        # Compensating release exactly as release-materials.
        calcs.release_consumption(run)
        for order in DB["orders"].values():
            if order["production_run_id"] == run["id"] \
                    and order["production_status"] == "SCHEDULED":
                order["production_status"] = "ACCEPTED"
                order["production_run_id"] = None
                touch(order)
        run["status"] = "CANCELLED"
        touch(run)
    elif run["status"] == "QUALITY_HOLD":
        # Materials are treated as physically consumed: lots NOT re-credited.
        for order in DB["orders"].values():
            if order["production_run_id"] == run["id"] \
                    and order["production_status"] in ("SCHEDULED", "IN_PRODUCTION"):
                order["production_status"] = "ACCEPTED"
                order["production_run_id"] = None
                touch(order)
        run["status"] = "CANCELLED"
        touch(run)
    else:
        raise ApiError(
            "ERR_INVALID_STATE",
            "only PLANNED, MATERIAL_RESERVED, or QUALITY_HOLD runs can be cancelled",
        )
    return ok_obj(serializers.pub(run))
