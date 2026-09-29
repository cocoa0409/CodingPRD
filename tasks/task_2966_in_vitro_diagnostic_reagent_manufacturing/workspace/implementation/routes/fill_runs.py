"""Filling runs, environmental monitoring and the compensating abort (PRD 3.4)."""

from datetime import timedelta

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, Body, ENVIRONMENTAL_STATES, FILL_RUN_STATUSES,
                        SAMPLE_TYPES, authenticate_and_authorize, bool_filter,
                        enum_filter, json_body, pagination, paginate, str_filter)

bp = Blueprint("fill_runs", __name__)

CHANGEOVER_BUFFER = timedelta(minutes=120)


@bp.post("/fill-runs")
def schedule_fill_run():
    authenticate_and_authorize(("ProductionOperator",))
    body = Body(json_body())
    reagent_lot_id = body.req_str("reagent_lot_id")
    line_code = body.req_str("line_code")
    formulation_batch_code = body.req_str("formulation_batch_code")
    scheduled_start = body.req_ts("scheduled_start")
    scheduled_end = body.req_ts("scheduled_end")
    if not scheduled_end > scheduled_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "scheduled_end must be strictly later than scheduled_start.")
    planned_fill_units = body.req_int("planned_fill_units", gt=0)

    # Rung 45 - body foreign keys.
    lookup.reagent_lot(reagent_lot_id)

    # Rung 100 - the 120-minute changeover buffer guards the line.
    for existing in rows(db.fill_runs):
        if existing["line_code"] != line_code:
            continue
        if existing["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if scheduled_start < existing["scheduled_end"] + CHANGEOVER_BUFFER and \
                existing["scheduled_start"] < scheduled_end + CHANGEOVER_BUFFER:
            raise ApiError("ERR_FILL_LINE_CONFLICT")

    row = create_row(db.fill_runs, {
        "reagent_lot_id": reagent_lot_id,
        "line_code": line_code,
        "formulation_batch_code": formulation_batch_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "planned_fill_units": planned_fill_units,
        "filled_units": None,
        "status": "SCHEDULED",
        "started_at": None,
        "ended_at": None,
        "minor_excursion_count": 0,
        "major_excursion_count": 0,
        "bioburden_cfu_per_ml": None,
        "environmental_state": "CONFORMING",
        "abort_reason": None,
    })
    return created_response(serialize.fill_run(row))


@bp.get("/fill-runs/<run_id>")
def read_fill_run(run_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.fill_run(run_id)
    return object_response(serialize.fill_run(row))


@bp.get("/fill-runs")
def list_fill_runs():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    reagent_lot_id = str_filter("reagent_lot_id")
    line_code = str_filter("line_code")
    status = enum_filter("status", FILL_RUN_STATUSES)
    environmental_state = enum_filter("environmental_state", ENVIRONMENTAL_STATES)
    items = rows(db.fill_runs)
    if reagent_lot_id is not None:
        items = [r for r in items if r["reagent_lot_id"] == reagent_lot_id]
    if line_code is not None:
        items = [r for r in items if r["line_code"] == line_code]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if environmental_state is not None:
        items = [r for r in items if r["environmental_state"] == environmental_state]
    page = paginate(items, limit, offset)
    return list_response([serialize.fill_run(r) for r in page],
                         limit, offset, len(items))


@bp.post("/fill-runs/<run_id>/start")
def start_fill_run(run_id):
    authenticate_and_authorize(("ProductionOperator",))
    json_body()
    run = lookup.fill_run(run_id)
    lot = db.reagent_lots[run["reagent_lot_id"]]

    # Rung 60 - state preconditions on the run and on the parent lot.
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_FILL_RUN_STATE_INVALID",
                       "A run in %s cannot be started." % run["status"])
    if lot["disposition_status"] != "PLANNED":
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "The parent lot is in %s." % lot["disposition_status"])
    if not calc.lot_components(lot["id"], "CONSUMED"):
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "The parent lot has an empty bill of materials.")

    run["status"] = "RUNNING"
    run["started_at"] = now_clock()
    touch(run)
    lot["disposition_status"] = "IN_PROCESS"
    touch(lot)
    return object_response(serialize.fill_run(run))


@bp.post("/fill-runs/<run_id>/complete")
def complete_fill_run(run_id):
    authenticate_and_authorize(("ProductionOperator",))
    body = Body(json_body())
    filled_units = body.req_int("filled_units", ge=0)
    run = lookup.fill_run(run_id)
    lot = db.reagent_lots[run["reagent_lot_id"]]

    # Rung 60 - state precondition.
    if run["status"] != "RUNNING":
        raise ApiError("ERR_FILL_RUN_STATE_INVALID",
                       "A run in %s cannot be completed." % run["status"])
    if filled_units > run["planned_fill_units"]:
        raise ApiError("ERR_FILL_RUN_STATE_INVALID",
                       "filled_units exceeds planned_fill_units.")
    samples = calc.run_samples(run["id"])
    if not any(s["sample_type"] == "BIOBURDEN_BULK" for s in samples):
        raise ApiError("ERR_FILL_RUN_STATE_INVALID",
                       "The run has no BIOBURDEN_BULK evidence.")

    clock = now_clock()
    # Hop 1 - the run closes out.
    run["status"] = "COMPLETED"
    run["filled_units"] = filled_units
    run["ended_at"] = clock
    recompute.fill_run_environment(run)
    touch(run)

    # Hop 2 - the finished lot takes the units on.
    lot["filled_units"] = lot["filled_units"] + filled_units
    if lot["fill_completed_at"] is None:
        lot["fill_completed_at"] = clock
    lot["disposition_status"] = "FILLED"
    recompute.reagent_lot_units(lot)

    # Hop 3 - a disqualified run auto-rejects the lot on the spot.
    if run["environmental_state"] == "DISQUALIFIED":
        lot["disposition_status"] = "REJECTED"
        lot["available_units"] = 0
        lot["distribution_status"] = "WITHHELD"

    # Hop 4 - monitoring roll-ups and the bridging flag.
    recompute.reagent_lot_monitoring(lot)
    recompute.reagent_lot_bridging_required(lot)
    touch(lot)
    return object_response(serialize.fill_run(run))


@bp.post("/fill-runs/<run_id>/abort")
def abort_fill_run(run_id):
    authenticate_and_authorize(("ProductionOperator",))
    body = Body(json_body())
    abort_reason = body.req_str("abort_reason")
    run = lookup.fill_run(run_id)
    lot = db.reagent_lots[run["reagent_lot_id"]]

    # Rung 60 - state precondition.
    if run["status"] not in ("SCHEDULED", "RUNNING"):
        raise ApiError("ERR_FILL_RUN_STATE_INVALID",
                       "A run in %s cannot be aborted." % run["status"])
    was_running = run["status"] == "RUNNING"

    # Hop 1 - the run aborts.
    run["status"] = "ABORTED"
    run["ended_at"] = now_clock()
    run["abort_reason"] = abort_reason
    touch(run)

    # Hop 2 - a RUNNING run's abort reverts the lot, unless another run is live.
    if was_running and lot["disposition_status"] == "IN_PROCESS":
        others_running = [r for r in calc.lot_runs(lot["id"])
                          if r["id"] != run["id"] and r["status"] == "RUNNING"]
        if not others_running:
            lot["disposition_status"] = "PLANNED"

    # Hops 3 and 4 - the compensation of the raw material ledger.
    for component in calc.lot_components(lot["id"], "CONSUMED"):
        component["status"] = "RETURNED"
        touch(component)
        material_lot = db.material_lots.get(component["material_lot_id"])
        if material_lot is not None:
            recompute.material_lot_quantities(material_lot)
            touch(material_lot)

    recompute.reagent_lot_bridging_required(lot)
    touch(lot)
    return object_response(serialize.fill_run(run))


@bp.post("/fill-runs/<run_id>/samples")
def record_sample(run_id):
    authenticate_and_authorize(("QCAnalyst",))
    body = Body(json_body())
    sample_type = body.req_enum("sample_type", SAMPLE_TYPES)
    location_code = body.req_str("location_code")
    result_value = body.req_number("result_value", ge=0)
    sampled_at = body.req_ts("sampled_at")
    run = lookup.fill_run(run_id)
    lot = db.reagent_lots[run["reagent_lot_id"]]

    # Rung 60 - a sample is a self-loop on SCHEDULED or RUNNING.
    if run["status"] not in ("SCHEDULED", "RUNNING"):
        raise ApiError("ERR_FILL_RUN_STATE_INVALID",
                       "A run in %s cannot be sampled." % run["status"])

    limit_value, excursion, grade = calc.sample_derivations(sample_type, result_value)
    sample = create_row(db.monitoring_samples, {
        "fill_run_id": run["id"],
        "sample_type": sample_type,
        "location_code": location_code,
        "result_value": result_value,
        "sampled_at": sampled_at,
        "limit_value": limit_value,
        "excursion": excursion,
        "excursion_grade": grade,
    }, common=False)

    recompute.fill_run_environment(run)
    touch(run)
    recompute.reagent_lot_monitoring(lot)
    touch(lot)
    return created_response(serialize.monitoring_sample(sample))


@bp.get("/fill-runs/<run_id>/samples")
def list_samples(run_id):
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    sample_type = enum_filter("sample_type", SAMPLE_TYPES)
    excursion = bool_filter("excursion")
    run = lookup.fill_run(run_id)
    items = calc.run_samples(run["id"])
    if sample_type is not None:
        items = [s for s in items if s["sample_type"] == sample_type]
    if excursion is not None:
        items = [s for s in items if s["excursion"] == excursion]
    page = paginate(items, limit, offset)
    return list_response([serialize.monitoring_sample(s) for s in page],
                         limit, offset, len(items))
