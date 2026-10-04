"""BlendRun routes (PRD 3.4): create / read / commit / void.

Commit semantics:
- formula must be ACTIVE at commit time (ERR_FORMULA_NOT_ACTIVE)
- ERR_NO_QUALIFYING_LOTS / ERR_INSUFFICIENT_LOT_QUANTITY abort before any
  computed field exists and persist nothing
- OUT_OF_SPEC persists the computed fields it reached, status stays DRAFT,
  no lot quantities change, version increments
- success atomically consumes lot quantities (remaining -> consumed), lots
  reaching exactly 0 remaining go ACCEPTED -> DEPLETED, version increments
- void of COMMITTED restores quantities; DEPLETED lots above 0 -> ACCEPTED.
"""
from flask import Blueprint

from errors import ApiError
from helpers import (F, filter_enum, invalid_state, new_entity, not_found,
                     paged, pub, q3, require_roles, respond, touch,
                     validate_body, validation_error)
from services.blend import select_allocations
from state import DB

bp = Blueprint("blend_runs", __name__)

BLEND_RUN_STATUSES = ["DRAFT", "COMMITTED", "VOIDED"]


@bp.post("/spice/blend-runs")
@require_roles("FlavorScientist")
def create_blend_run():
    data = validate_body({
        "formula_id": F("str", required=True),
        "selection_policy": F("enum", enum=["COST_MIN", "FIFO_AGE"], required=True),
        "target_batch_kg": F("num", required=True),
    })
    if data["target_batch_kg"] <= 0:
        validation_error("target_batch_kg must be > 0")
    formula = DB.formulas.get(data["formula_id"])
    if formula is None:
        not_found("formula not found")
    if formula["status"] != "ACTIVE":
        raise ApiError("ERR_FORMULA_NOT_ACTIVE", 409,
                       "Blend runs require an ACTIVE formula")
    run = new_entity({
        "formula_id": data["formula_id"],
        "selection_policy": data["selection_policy"],
        "target_batch_kg": q3(data["target_batch_kg"]),
        "status": "DRAFT",
        "selected_allocations": None,
        "residual_flavor_pct": None,
        "blended_moisture_pct": None,
        "cost_total_cents": None,
        "spec_status": None,
    })
    DB.blend_runs[run["id"]] = run
    return respond(pub(run), 201)


@bp.get("/spice/blend-runs/<run_id>")
@require_roles("FlavorScientist", "ProductionScheduler")
def get_blend_run(run_id):
    run = DB.blend_runs.get(run_id)
    if run is None:
        not_found("blend run not found")
    return respond(pub(run))


@bp.get("/spice/blend-runs")
@require_roles("FlavorScientist", "ProductionScheduler")
def list_blend_runs():
    from flask import request
    formula_id = request.args.get("formula_id")
    status = filter_enum("status", BLEND_RUN_STATUSES)
    items = []
    for r in DB.blend_runs.values():
        if formula_id is not None and r["formula_id"] != formula_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    data, meta = paged(items)
    return respond(data, page=meta)


@bp.post("/spice/blend-runs/<run_id>/commit")
@require_roles("FlavorScientist")
def commit_blend_run(run_id):
    run = DB.blend_runs.get(run_id)
    if run is None:
        not_found("blend run not found")
    if run["status"] != "DRAFT":
        invalid_state("Only a DRAFT blend run can be committed")
    formula = DB.formulas.get(run["formula_id"])
    if formula is None or formula["status"] != "ACTIVE":
        raise ApiError("ERR_FORMULA_NOT_ACTIVE", 409,
                       "Referenced formula is not ACTIVE")
    # Candidate-pool / insufficient-quantity failures raise here, before any
    # computed field exists — nothing persists.
    allocations, residual, moisture3, cost_total, spec_status = \
        select_allocations(run, formula)
    run["selected_allocations"] = allocations
    run["residual_flavor_pct"] = residual
    run["blended_moisture_pct"] = moisture3
    run["cost_total_cents"] = cost_total
    run["spec_status"] = spec_status
    if spec_status == "OUT_OF_SPEC":
        # Persisted failure: computed fields persist, status stays DRAFT,
        # no lot quantities change, version increments.
        touch(run)
        raise ApiError("ERR_BLEND_OUT_OF_SPEC", 422,
                       "Blend is out of specification")
    # Success: atomically consume lot quantities.
    for a in allocations:
        lot = DB.lots[a["lot_id"]]
        lot["quantity_remaining_kg"] -= a["allocated_kg"]
        lot["quantity_consumed_kg"] += a["allocated_kg"]
        if lot["quantity_remaining_kg"] == 0 and lot["status"] == "ACCEPTED":
            lot["status"] = "DEPLETED"
        touch(lot)
    run["status"] = "COMMITTED"
    touch(run)
    return respond(pub(run))


@bp.post("/spice/blend-runs/<run_id>/void")
@require_roles("FlavorScientist")
def void_blend_run(run_id):
    run = DB.blend_runs.get(run_id)
    if run is None:
        not_found("blend run not found")
    if run["status"] == "DRAFT":
        pass  # nothing was consumed; no lot quantity changes
    elif run["status"] == "COMMITTED":
        blocking = any(
            r["blend_run_id"] == run_id and r["status"] == "COMPLETED"
            for r in DB.production_runs.values())
        if blocking:
            invalid_state("A COMPLETED production run references this blend run")
        for a in (run["selected_allocations"] or []):
            lot = DB.lots[a["lot_id"]]
            lot["quantity_consumed_kg"] -= a["allocated_kg"]
            lot["quantity_remaining_kg"] += a["allocated_kg"]
            if lot["status"] == "DEPLETED" and lot["quantity_remaining_kg"] > 0:
                lot["status"] = "ACCEPTED"
            touch(lot)
    else:
        invalid_state("A %s blend run cannot be voided" % run["status"])
    run["status"] = "VOIDED"
    touch(run)
    return respond(pub(run))
