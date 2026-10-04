"""ProductionRun scheduling (OCC-guarded), completion and cancellation
(PRD 3.5-3.6). Validation follows the PRD 2.8 pipeline order:
shape -> ranges -> existence -> OCC (412) -> changeover support (409) ->
formula ACTIVE (409) -> blend COMMITTED (409) -> window conflict (409) ->
agreement required (422) -> product in agreement (422) -> quantity match (422)
-> formula match (422) -> weekly capacity (409).
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from errors import ApiError
from helpers import (F, filter_enum, invalid_state, new_entity, not_found,
                     paged, pub, q3, require_roles, respond, touch,
                     validate_body, validation_error)
from services.capacity import (changeover_class, find_predecessor, free_kg,
                               week_monday)
from state import DB

bp = Blueprint("production_runs", __name__)

RUN_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
RUN_READ_ROLES = ("ProductionScheduler", "QualityManager", "RecallCoordinator",
                  "SupplyPlanner")
SHELF_LIFE_DAYS = 540


@bp.post("/spice/production-runs")
@require_roles("ProductionScheduler")
def create_run():
    data = validate_body({
        "line_id": F("str", required=True),
        "formula_id": F("str", required=True),
        "blend_run_id": F("str", required=True),
        "private_label_agreement_id": F("str", nullable=True, default=None),
        "quantity_kg": F("num", required=True),
        "window_start": F("dt", required=True),
        "window_end": F("dt", required=True),
        "expected_line_version": F("int", required=True),
    })
    if data["quantity_kg"] <= 0:
        validation_error("quantity_kg must be > 0")
    if not data["window_end"] > data["window_start"]:
        validation_error("window_end must be strictly after window_start")
    line = DB.production_lines.get(data["line_id"])
    if line is None:
        not_found("production line not found")
    formula = DB.formulas.get(data["formula_id"])
    if formula is None:
        not_found("formula not found")
    brun = DB.blend_runs.get(data["blend_run_id"])
    if brun is None:
        not_found("blend run not found")
    agreement = None
    if data["private_label_agreement_id"] is not None:
        agreement = DB.agreements.get(data["private_label_agreement_id"])
        if agreement is None:
            not_found("private label agreement not found")
    # OCC: expected_line_version must equal the line's current version.
    if data["expected_line_version"] != line["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_line_version does not match the line's current version")
    # Changeover: computed against the predecessor; must be supported.
    pred = find_predecessor(line["id"], data["window_start"])
    cls = changeover_class(pred, formula, data["private_label_agreement_id"])
    if cls not in line["supported_changeover_classes"]:
        raise ApiError("ERR_ALLERGEN_CHANGEOVER_INSUFFICIENT", 409,
                       "Required changeover class %s is not supported by the line" % cls)
    if formula["status"] != "ACTIVE":
        raise ApiError("ERR_FORMULA_NOT_ACTIVE", 409,
                       "Referenced formula is not ACTIVE")
    if brun["status"] != "COMMITTED":
        raise ApiError("ERR_BLEND_RUN_NOT_COMMITTED", 409,
                       "Referenced blend run is not COMMITTED")
    # Half-open window exclusivity on the line; adjacency is allowed.
    for r in DB.production_runs.values():
        if r["line_id"] == line["id"] and r["status"] != "CANCELLED":
            if data["window_start"] < r["window_end"] and r["window_start"] < data["window_end"]:
                raise ApiError("ERR_LINE_WINDOW_CONFLICT", 409,
                               "Window intersects an existing run on this line")
    if (formula["brand_type"] == "PRIVATE_LABEL"
            and data["private_label_agreement_id"] is None):
        raise ApiError("ERR_AGREEMENT_REQUIRED", 422,
                       "PRIVATE_LABEL runs require private_label_agreement_id")
    if agreement is not None and formula["product_code"] not in agreement["product_codes"]:
        raise ApiError("ERR_PRODUCT_NOT_IN_AGREEMENT", 422,
                       "Formula product_code is not covered by the agreement")
    qty = q3(data["quantity_kg"])
    if qty != brun["target_batch_kg"]:
        raise ApiError("ERR_QUANTITY_MISMATCH", 422,
                       "quantity_kg must equal the blend run's target_batch_kg")
    if data["formula_id"] != brun["formula_id"]:
        raise ApiError("ERR_FORMULA_MISMATCH", 422,
                       "formula_id must equal the blend run's formula_id")
    # Weekly capacity pool: the run consumes the ISO week of window_start.
    monday = week_monday(data["window_start"])
    if free_kg(line, monday) - qty < 0:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "Scheduling this run would drive the weekly pool negative")
    run = new_entity({
        "line_id": data["line_id"],
        "formula_id": data["formula_id"],
        "blend_run_id": data["blend_run_id"],
        "private_label_agreement_id": data["private_label_agreement_id"],
        "quantity_kg": qty,
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "predecessor_run_id": pred["id"] if pred else None,
        "changeover_class_required": cls,
        "status": "SCHEDULED",
    })
    DB.production_runs[run["id"]] = run
    touch(line)  # successful scheduling increments the line's version by 1
    return respond(pub(run), 201)


@bp.get("/spice/production-runs/<run_id>")
@require_roles(*RUN_READ_ROLES)
def get_run(run_id):
    run = DB.production_runs.get(run_id)
    if run is None:
        not_found("production run not found")
    return respond(pub(run))


@bp.get("/spice/production-runs")
@require_roles(*RUN_READ_ROLES)
def list_runs():
    line_id = request.args.get("line_id")
    formula_id = request.args.get("formula_id")
    blend_run_id = request.args.get("blend_run_id")
    agreement_id = request.args.get("private_label_agreement_id")
    status = filter_enum("status", RUN_STATUSES)
    items = []
    for r in DB.production_runs.values():
        if line_id is not None and r["line_id"] != line_id:
            continue
        if formula_id is not None and r["formula_id"] != formula_id:
            continue
        if blend_run_id is not None and r["blend_run_id"] != blend_run_id:
            continue
        if agreement_id is not None and r["private_label_agreement_id"] != agreement_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    data, meta = paged(items)
    return respond(data, page=meta)


@bp.post("/spice/production-runs/<run_id>/complete")
@require_roles("ProductionScheduler")
def complete_run(run_id):
    run = DB.production_runs.get(run_id)
    if run is None:
        not_found("production run not found")
    if run["status"] != "SCHEDULED":
        invalid_state("Only a SCHEDULED run can be completed")
    run["status"] = "COMPLETED"
    touch(run)
    formula = DB.formulas[run["formula_id"]]
    brun = DB.blend_runs[run["blend_run_id"]]
    produced_at = DB.clock
    genealogy = []
    for a in (brun["selected_allocations"] or []):
        if a["lot_id"] not in genealogy:
            genealogy.append(a["lot_id"])
    batch = new_entity({
        "production_run_id": run["id"],
        "product_code": formula["product_code"],
        "brand_type": formula["brand_type"],
        "quantity_kg": run["quantity_kg"],
        "produced_at": produced_at,
        "shelf_life_days": SHELF_LIFE_DAYS,
        "best_by_date": produced_at + timedelta(days=SHELF_LIFE_DAYS),
        "genealogy_lot_ids": genealogy,
        "unit_cost_cents": brun["cost_total_cents"],
        "commercial_status": "CREATED",
        "quality_status": "CLEAR",
        "quality_hold_cause": "NONE",
        "quality_hold_lot_id": None,
    })
    DB.batches[batch["id"]] = batch
    if run["private_label_agreement_id"]:
        ag = DB.agreements.get(run["private_label_agreement_id"])
        if ag is not None:
            ag["produced_ytd_kg"] += run["quantity_kg"]
            ag["commitment_met"] = ag["produced_ytd_kg"] >= ag["annual_commitment_kg"]
            touch(ag)
    return respond(pub(run))


@bp.post("/spice/production-runs/<run_id>/cancel")
@require_roles("ProductionScheduler")
def cancel_run(run_id):
    run = DB.production_runs.get(run_id)
    if run is None:
        not_found("production run not found")
    if run["status"] != "SCHEDULED":
        invalid_state("Only a SCHEDULED run can be cancelled")
    run["status"] = "CANCELLED"  # its quantity stops consuming the weekly pool
    touch(run)
    return respond(pub(run))
