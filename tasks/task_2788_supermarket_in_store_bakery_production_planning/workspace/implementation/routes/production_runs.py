"""Production run endpoints: manual scheduling and the execution path
(PRD 3.4, 3.5, 3.6)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    DISPOSITION_STATUSES,
    EXECUTION_STATUSES,
    as_datetime,
    as_decimal,
    as_int,
    authenticate,
    bad,
    body,
    enum_filter,
    find_bake_day,
    find_oven,
    find_product,
    find_run,
    scope,
)
from response import created, listing, ok, parse_pagination, touch
from services.calc import bake_interval, deck_collides, markdown_unit_price_cents, planned_labor_minutes
from services.plan import oven_accepts
from services.rollups import recompute_bake_day, recompute_labels
from services.runs import complete_run, create_run
from store import by_seq, db
from util import add_hours, add_minutes, dec, q2

bp = Blueprint("production_runs", __name__)


def guard_execution_day(day):
    """Execution writes: never on a CLOSED day, never on a DRAFT day."""
    if day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")
    if day["plan_posture"] not in ("PLANNED", "LOCKED"):
        raise ApiError("ERR_INVALID_RUN_STATE", "The day has no generated plan yet.")


def guard_allergens(oven, product):
    if oven is None:
        return
    if not oven_accepts(oven, product):
        raise ApiError("ERR_ALLERGEN_SEGREGATION_VIOLATION")


@bp.post("/bakery/production-runs")
def create_production_run():
    caller = authenticate(("DepartmentManager", "Baker"))
    payload = body()
    day = find_bake_day(payload.get("bake_day_id"))
    scope(caller, day["department_id"])
    product = find_product(payload.get("product_id"))
    oven = None
    if payload.get("oven_id") is not None:
        oven = find_oven(payload.get("oven_id"))

    # band 5 -- shape
    rack_count = as_int(payload, "rack_count", minimum=1)
    method = product["production_method"]
    oven_required = method in ("SCRATCH", "PAR_BAKED")
    mismatched = (oven_required and oven is None) or (not oven_required and oven is not None)
    deck_index = None
    proof_start = None
    bake_start = None
    if not mismatched:
        if oven is not None:
            deck_index = as_int(payload, "deck_index")
        elif payload.get("deck_index") is not None:
            bad("deck_index", "must be null when no oven is named.")
        if method == "SCRATCH":
            proof_start = as_datetime(payload, "proof_start_utc")
        elif payload.get("proof_start_utc") is not None:
            bad("proof_start_utc", "must be null for a %s product." % method)
        if oven_required:
            bake_start = as_datetime(payload, "bake_start_utc")
        elif payload.get("bake_start_utc") is not None:
            bad("bake_start_utc", "must be null for a THAW_AND_SERVE product.")
    else:
        deck_index = as_int(payload, "deck_index", required=False, default=None)
        proof_start = as_datetime(payload, "proof_start_utc", required=False, default=None)
        bake_start = as_datetime(payload, "bake_start_utc", required=False, default=None)

    # band 7 -- own-entity state
    if day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")
    if day["plan_posture"] == "LOCKED":
        raise ApiError("ERR_BAKE_DAY_PLAN_LOCKED")

    # band 8 -- cross-entity state
    if oven is not None and oven["oven_status"] != "AVAILABLE":
        raise ApiError("ERR_OVEN_UNAVAILABLE")

    # band 9 -- safety
    guard_allergens(oven, product)

    # band 10 -- temporal
    if not mismatched:
        if proof_start is not None and proof_start < day["oven_shift_start_utc"]:
            raise ApiError("ERR_OVEN_SHIFT_WINDOW_VIOLATION")
        if bake_start is not None:
            tail = add_minutes(bake_start, int(product["bake_minutes"]) + int(product["cool_minutes"]))
            if tail > day["oven_shift_end_utc"]:
                raise ApiError("ERR_OVEN_SHIFT_WINDOW_VIOLATION")
        if oven is not None and bake_start is not None:
            end = add_minutes(bake_start, int(product["bake_minutes"]))
            if deck_collides(oven, deck_index, bake_start, end):
                raise ApiError("ERR_OVEN_SLOT_CONFLICT")

    # band 11 -- constraint satisfaction
    if oven is not None and deck_index is not None:
        if deck_index < 0 or deck_index >= int(oven["deck_count"]):
            raise ApiError("ERR_DECK_INDEX_OUT_OF_RANGE")

    # band 12 -- referential
    if product["department_id"] != day["department_id"]:
        raise ApiError("ERR_INGREDIENT_NOT_IN_DEPARTMENT", "The product belongs to another department.")
    if oven is not None and oven["department_id"] != day["department_id"]:
        raise ApiError("ERR_INGREDIENT_NOT_IN_DEPARTMENT", "The oven belongs to another department.")
    if mismatched:
        raise ApiError("ERR_OVEN_METHOD_MISMATCH")

    # band 13 -- fiscal and capacity
    if oven is not None and rack_count > int(oven["rack_capacity_per_deck"]):
        raise ApiError("ERR_OVEN_RACK_CAPACITY_EXCEEDED")
    planned = planned_labor_minutes(product, rack_count)
    if q2(dec(day["planned_labor_minutes"]) + dec(planned)) > dec(day["labor_budget_minutes"]):
        raise ApiError("ERR_LABOR_BUDGET_EXCEEDED")

    run = create_run(day, product, oven, deck_index, rack_count, proof_start, bake_start, "MANUAL")
    recompute_bake_day(day)
    return created(serializers.production_run(run))


@bp.get("/bakery/production-runs/<runId>")
def read_run(runId):
    authenticate(ANY_ROLE)
    return ok(serializers.production_run(find_run(runId)))


@bp.get("/bakery/production-runs")
def list_runs():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    bake_day_id = request.args.get("bake_day_id") or None
    product_id = request.args.get("product_id") or None
    oven_id = request.args.get("oven_id") or None
    execution_status = enum_filter(request.args, "execution_status", EXECUTION_STATUSES)
    disposition_status = enum_filter(request.args, "disposition_status", DISPOSITION_STATUSES)
    rows = []
    for row in db.runs.values():
        if bake_day_id is not None and row["bake_day_id"] != bake_day_id:
            continue
        if product_id is not None and row["product_id"] != product_id:
            continue
        if oven_id is not None and row.get("oven_id") != oven_id:
            continue
        if execution_status is not None and row["execution_status"] != execution_status:
            continue
        if disposition_status is not None and row["disposition_status"] != disposition_status:
            continue
        rows.append(row)
    return listing([serializers.production_run(row) for row in by_seq(rows)], limit, offset)


def _context(run):
    day = db.bake_days.get(run["bake_day_id"])
    product = db.products.get(run["product_id"])
    oven = db.ovens.get(run["oven_id"]) if run.get("oven_id") else None
    return day, product, oven


@bp.post("/bakery/production-runs/<runId>/start-proof")
def start_proof(runId):
    authenticate(("Baker",))
    run = find_run(runId)
    day, product, oven = _context(run)

    guard_execution_day(day)
    if run["execution_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_RUN_STATE", "Only a SCHEDULED run may begin proofing.")
    if product["production_method"] != "SCRATCH" or int(product["proof_minutes"]) <= 0:
        raise ApiError("ERR_PROOF_NOT_REQUIRED")
    if oven is not None and oven["oven_status"] != "AVAILABLE":
        raise ApiError("ERR_OVEN_UNAVAILABLE")

    run["execution_status"] = "PROOFING"
    touch(run)
    return ok(serializers.production_run(run))


@bp.post("/bakery/production-runs/<runId>/start-bake")
def start_bake(runId):
    authenticate(("Baker",))
    run = find_run(runId)
    day, product, oven = _context(run)
    method = product["production_method"]

    guard_execution_day(day)
    if run["execution_status"] not in ("SCHEDULED", "PROOFING"):
        raise ApiError("ERR_INVALID_RUN_STATE", "The run may no longer be loaded into a deck.")
    if method != "SCRATCH" and run["execution_status"] == "PROOFING":
        raise ApiError("ERR_INVALID_RUN_STATE", "This run does not proof.")
    if method == "SCRATCH" and run["execution_status"] == "SCHEDULED":
        raise ApiError("ERR_PROOF_REQUIRED")
    if oven is not None and oven["oven_status"] != "AVAILABLE":
        raise ApiError("ERR_OVEN_UNAVAILABLE")
    guard_allergens(oven, product)
    if method == "THAW_AND_SERVE":
        raise ApiError("ERR_OVEN_METHOD_MISMATCH", "A thaw-and-serve run never enters an oven.")

    run["execution_status"] = "BAKING"
    touch(run)
    if run.get("oven_id"):
        recompute_labels(run["oven_id"], run["bake_day_id"])
    return ok(serializers.production_run(run))


@bp.post("/bakery/production-runs/<runId>/complete")
def complete(runId):
    caller = authenticate(("Baker",))
    run = find_run(runId)
    day, product, _oven = _context(run)
    payload = body()
    actual_units = as_int(payload, "actual_units", minimum=0)
    actual_labor = as_decimal(payload, "actual_labor_minutes", required=False, minimum=0, default=None)

    guard_execution_day(day)
    method = product["production_method"]
    if method == "THAW_AND_SERVE":
        if run["execution_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_RUN_STATE", "This run may no longer be completed.")
    elif run["execution_status"] != "BAKING":
        raise ApiError("ERR_INVALID_RUN_STATE", "Only a BAKING run may be completed.")

    complete_run(run, product, day, actual_units, actual_labor, caller)
    return ok(serializers.production_run(run))


@bp.post("/bakery/production-runs/<runId>/markdown")
def markdown(runId):
    caller = authenticate(("DepartmentManager", "Baker"))
    run = find_run(runId)
    day, product, _oven = _context(run)
    scope(caller, day["department_id"])

    guard_execution_day(day)
    if run["execution_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_RUN_STATE", "Only a COMPLETED run may be marked down.")
    if run["disposition_status"] != "ON_SHELF" or int(run["on_shelf_units"] or 0) < 1:
        raise ApiError("ERR_INVALID_RUN_STATE", "The run has no shelf stock to discount.")

    now = db.now()
    expires = run["expires_utc"]
    if now >= expires:
        raise ApiError("ERR_PRODUCT_EXPIRED")
    if now < add_hours(expires, -4):
        raise ApiError("ERR_MARKDOWN_WINDOW_NOT_OPEN")

    if day["markdown_authorization"] == "MANAGER_ONLY" and caller.role != "DepartmentManager":
        raise ApiError("ERR_MARKDOWN_AUTHORIZATION_REQUIRED")

    run["markdown_unit_price_cents"] = markdown_unit_price_cents(product)
    run["disposition_status"] = "MARKED_DOWN"
    touch(run)
    return ok(serializers.production_run(run))
