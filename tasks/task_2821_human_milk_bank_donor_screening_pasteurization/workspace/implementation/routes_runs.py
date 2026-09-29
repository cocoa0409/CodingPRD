"""Pasteurization run control, thermal readings, culture and bottling.

Endpoints (8): POST/GET /pasteurization-runs, GET /pasteurization-runs/{id},
POST/GET /pasteurization-runs/{id}/readings,
POST /pasteurization-runs/{id}/complete,
POST /pasteurization-runs/{id}/culture,
POST /pasteurization-runs/{id}/lots.
"""

from datetime import timedelta

from flask import Blueprint

import domain_pool
import domain_run
import serializers
from auth import (ADMIN, MEDICAL_DIRECTOR, PROCESSING_TECHNICIAN, QA_OFFICER,
                  actor_id, guard)
from envelope import ok, page, pagination
from errors import fail, not_found
from listing import apply_filters, sort_by
from store import db, find, insert, set_field
from util import fmt_instant
from validate import field, json_body, validate

bp = Blueprint("runs", __name__)

RUN_READERS = (PROCESSING_TECHNICIAN, QA_OFFICER, ADMIN)
RUN_DETAIL_READERS = (PROCESSING_TECHNICIAN, QA_OFFICER, MEDICAL_DIRECTOR, ADMIN)


def run_or_404(run_id):
    run = find("runs", run_id)
    if run is None:
        not_found("Pasteurization run '%s' does not exist." % run_id)
    return run


def run_state_invalid(message):
    fail("ERR_RUN_STATE_INVALID", message)


# --- POST /pasteurization-runs --------------------------------------------
@bp.route("/pasteurization-runs", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def create_run():
    body = json_body()
    raw_pool_id = body.get("pool_id")
    pool = None
    if isinstance(raw_pool_id, str):
        pool = find("pools", raw_pool_id)
        if pool is None:
            not_found("Pool '%s' does not exist." % raw_pool_id)

    values = validate(body, [
        field("pool_id", "string"),
        field("pasteurizer_id", "string", regex=r"^PAST-[0-9]{2}$"),
        field("scheduled_start_at", "datetime"),
        field("cycle_minutes", "integer", min=30, max=120),
    ])
    if pool["status"] != "COMMITTED":
        fail("ERR_POOL_STATE_INVALID",
             "A pool in %s may not be pasteurized." % pool["status"])

    start = values["scheduled_start_at"]
    end = start + timedelta(
        minutes=values["cycle_minutes"] + domain_run.CLEANING_BUFFER_MINUTES)
    if domain_run.slot_conflict(values["pasteurizer_id"], start, end):
        fail("ERR_PASTEURIZER_SLOT_CONFLICT",
             "Pasteurizer %s is occupied over that interval."
             % values["pasteurizer_id"])

    run = insert("runs", {
        "pool_id": pool["id"],
        "pasteurizer_id": values["pasteurizer_id"],
        "scheduled_start_at": fmt_instant(values["scheduled_start_at"]),
        "cycle_minutes": values["cycle_minutes"],
        "run_status": "SCHEDULED",
        "thermal_status": "PENDING",
        "culture_status": "NOT_COLLECTED",
        "release_eligibility": "BLOCKED",
        "reading_count": 0,
        "longest_hold_seconds": None,
        "peak_celsius": None,
        "completed_at": None,
        "completed_by_user_id": None,
        "culture_cfu_per_ml": None,
        "culture_organism": None,
        "culture_recorded_by_user_id": None,
    })
    return ok(serializers.run_out(run), 201)


# --- GET /pasteurization-runs ---------------------------------------------
@bp.route("/pasteurization-runs", methods=["GET"])
@guard(*RUN_READERS)
def list_runs():
    limit, offset = pagination()
    rows = apply_filters(db.rows("runs"),
                         [("pool_id", "pool_id", "str"),
                          ("run_status", "run_status", "str"),
                          ("pasteurizer_id", "pasteurizer_id", "str")])
    sort_by(rows, [(lambda r: r["scheduled_start_at"], False),
                   (lambda r: r["created_at"], False),
                   (lambda r: r["_seq"], False)])
    return page(rows, limit, offset, serializers.run_out)


# --- GET /pasteurization-runs/{id} ----------------------------------------
@bp.route("/pasteurization-runs/<run_id>", methods=["GET"])
@guard(*RUN_DETAIL_READERS)
def get_run(run_id):
    return ok(serializers.run_out(run_or_404(run_id)))


# --- GET /pasteurization-runs/{id}/readings -------------------------------
@bp.route("/pasteurization-runs/<run_id>/readings", methods=["GET"])
@guard(*RUN_READERS)
def list_readings(run_id):
    run = run_or_404(run_id)
    limit, offset = pagination()
    rows = apply_filters(domain_run.readings_of(run["id"]),
                         [("qualifies", "qualifies", "bool")])
    sort_by(rows, [(lambda r: r["offset_seconds"], False)])
    return page(rows, limit, offset, serializers.reading_out)


# --- POST /pasteurization-runs/{id}/readings ------------------------------
@bp.route("/pasteurization-runs/<run_id>/readings", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def create_reading(run_id):
    run = run_or_404(run_id)
    body = json_body()
    values = validate(body, [
        field("offset_seconds", "integer", min=0, max=14400),
        field("celsius", "number", min="0.0", max="90.0"),
    ])
    if run["run_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        run_state_invalid("A run in %s accepts no readings." % run["run_status"])
    existing = domain_run.readings_of(run["id"])
    for reading in existing:
        if values["offset_seconds"] <= reading["offset_seconds"]:
            fail("ERR_READING_SEQUENCE_INVALID",
                 "offset_seconds must exceed every recorded offset.")

    reading = insert("readings", {
        "run_id": run["id"],
        "offset_seconds": values["offset_seconds"],
        "celsius": values["celsius"],
        "qualifies": domain_run.qualifies(values["celsius"]),
        "recorded_by_user_id": actor_id(),
    })
    set_field(run, "run_status", "IN_PROGRESS")
    set_field(run, "reading_count", run["reading_count"] + 1)
    domain_run.refresh_peak(run)
    return ok(serializers.reading_out(reading), 201)


# --- POST /pasteurization-runs/{id}/complete ------------------------------
@bp.route("/pasteurization-runs/<run_id>/complete", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def complete_run(run_id):
    run = run_or_404(run_id)
    if run["run_status"] != "IN_PROGRESS":
        run_state_invalid("A run in %s may not be completed." % run["run_status"])
    if len(domain_run.readings_of(run["id"])) < domain_run.MIN_READINGS_TO_COMPLETE:
        fail("ERR_RUN_READINGS_INSUFFICIENT",
             "At least %d readings are required to complete a run."
             % domain_run.MIN_READINGS_TO_COMPLETE)

    longest = domain_run.thermal_hold_seconds(run)
    set_field(run, "longest_hold_seconds", longest)
    set_field(run, "thermal_status",
              "PASSED" if longest >= domain_run.MIN_HOLD_SECONDS else "FAILED")
    domain_run.refresh_peak(run)
    set_field(run, "run_status", "COMPLETED")
    set_field(run, "completed_at", db.clock_instant())
    set_field(run, "completed_by_user_id", actor_id())
    domain_run.refresh_release_eligibility(run)
    return ok(serializers.run_out(run))


# --- POST /pasteurization-runs/{id}/culture -------------------------------
@bp.route("/pasteurization-runs/<run_id>/culture", methods=["POST"])
@guard(QA_OFFICER)
def record_culture(run_id):
    run = run_or_404(run_id)
    body = json_body()
    values = validate(body, [
        field("culture_cfu_per_ml", "integer"),
        field("culture_organism", "string"),
    ])
    if run["run_status"] not in ("COMPLETED", "BOTTLED"):
        run_state_invalid("A run in %s accepts no culture." % run["run_status"])
    if run["culture_status"] != "NOT_COLLECTED":
        run_state_invalid("This run's culture has already been recorded.")

    set_field(run, "culture_cfu_per_ml", values["culture_cfu_per_ml"])
    set_field(run, "culture_organism", values["culture_organism"])
    set_field(run, "culture_recorded_by_user_id", actor_id())
    failed = values["culture_cfu_per_ml"] >= domain_run.CULTURE_FAIL_CFU
    set_field(run, "culture_status", "FAILED" if failed else "PASSED")
    domain_run.refresh_release_eligibility(run)
    if failed:
        domain_run.run_culture_failure(run)
    return ok(serializers.run_out(run))


# --- POST /pasteurization-runs/{id}/lots ----------------------------------
@bp.route("/pasteurization-runs/<run_id>/lots", methods=["POST"])
@guard(PROCESSING_TECHNICIAN)
def bottle_lot(run_id):
    run = run_or_404(run_id)
    body = json_body()
    values = validate(body, [
        field("bottle_count", "integer", min=1, max=200),
        field("bottle_volume_ml", "integer", min=20, max=250),
    ])
    if run["run_status"] not in ("COMPLETED", "BOTTLED") \
            or run["thermal_status"] != "PASSED":
        run_state_invalid(
            "Only a thermally passed, completed run may be bottled (run_status "
            "%s, thermal_status %s)." % (run["run_status"], run["thermal_status"]))

    pool = find("pools", run["pool_id"])
    if pool is None:
        not_found("Pool '%s' does not exist." % run["pool_id"])
    total_volume = values["bottle_count"] * values["bottle_volume_ml"]
    headroom = pool["total_volume_ml"] - pool["bottled_volume_ml"]
    if total_volume > headroom:
        fail("ERR_BOTTLING_EXCEEDS_POOL_VOLUME",
             "The pool holds only %d ml of unbottled milk." % headroom)

    lot = domain_run.bottle_lot(run, pool, values["bottle_count"],
                               values["bottle_volume_ml"])
    return ok(serializers.lot_out(lot), 201)
