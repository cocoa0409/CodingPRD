"""Packaging runs: the barrel ledger, completion and voiding."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate

bp = Blueprint("runs", __name__)

PACKAGE_TYPES = ("HALF_BBL_KEG", "QUARTER_BBL_KEG", "CAN_CASE_24")
DESTINATIONS = ("TAPROOM", "DISTRIBUTION")
RUN_STATES = ("PLANNED", "COMPLETED", "VOIDED")
RECONCILIATION_STATES = ("NOT_APPLICABLE", "OPEN", "RECONCILED")


@bp.get("/packaging-runs")
def list_runs():
    authenticate(ALL_ROLES)
    batch_id = validation.query_string("batch_id")
    state = validation.query_enum("state", RUN_STATES)
    destination = validation.query_enum("destination", DESTINATIONS)
    reconciliation_state = validation.query_enum("reconciliation_state", RECONCILIATION_STATES)

    def predicate(row):
        return (helpers.matches(row, "batch_id", batch_id)
                and helpers.matches(row, "state", state)
                and helpers.matches(row, "destination", destination)
                and helpers.matches(row, "reconciliation_state", reconciliation_state))

    rows, limit, offset, total = helpers.listing("runs", derive.serialize_run, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/packaging-runs/<run_id>")
def read_run(run_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_run(helpers.find("runs", run_id)))


@bp.post("/packaging-runs")
def create_run():
    authenticate(["CellarOperator"])
    payload = validation.body()
    batch_id = validation.field_id(payload, "batch_id")
    run_code = validation.field_string(payload, "run_code", 1, 24)
    package_type = validation.field_enum(payload, "package_type", PACKAGE_TYPES)
    destination = validation.field_enum(payload, "destination", DESTINATIONS)
    units_planned = validation.field_int(payload, "units_planned", minimum=1)
    expected_version = validation.field_int(payload, "expected_batch_version")

    batch = helpers.find("batches", batch_id)
    helpers.unique("runs", run_code)
    if expected_version != int(batch.get("version")):
        raise ApiError("ERR_STALE_BATCH_VERSION")
    if batch.get("state") != "CONDITIONING":
        raise ApiError("ERR_BATCH_NOT_CONDITIONING")

    row = store.new_row({
        "batch_id": batch_id,
        "run_code": run_code,
        "package_type": package_type,
        "destination": destination,
        "units_planned": units_planned,
        "units_produced": None,
        "bbl_removed": calc.bbl(0),
        "removed_at_utc": None,
        "state": "PLANNED",
        "kegs_filled_count": 0,
        "reconciliation_state": "NOT_APPLICABLE",
        "keg_shrinkage_oz": None,
        "loss_share_bbl": None,
        "certified_by_user_id": None,
        "voided_at_utc": None,
    })
    helpers.insert("runs", row)
    store.touch(batch)
    return envelope.object_response(derive.serialize_run(row), 201)


@bp.post("/packaging-runs/<run_id>/complete")
def complete_run(run_id):
    user_id, _role = authenticate(["CellarOperator"])
    payload = validation.body()
    units_produced = validation.field_int(payload, "units_produced", minimum=1)
    run = helpers.find("runs", run_id)
    if run.get("state") != "PLANNED":
        raise ApiError("ERR_RUN_TRANSITION_INVALID")
    helpers.require_notice_active()
    batch = helpers.find("batches", run["batch_id"])
    if batch.get("state") != "CONDITIONING":
        raise ApiError("ERR_BATCH_NOT_CONDITIONING")

    bbl_removed = calc.bbl(Decimal(units_produced) * calc.BBL_PER_UNIT[run["package_type"]])
    if bbl_removed > derive.remaining_bbl(batch):
        raise ApiError("ERR_UNITS_EXCEED_BATCH_VOLUME")

    seen = set()
    run["state"] = "COMPLETED"
    run["units_produced"] = units_produced
    run["bbl_removed"] = bbl_removed
    run["removed_at_utc"] = helpers.now()
    run["certified_by_user_id"] = user_id
    cascades.touch_once(run, seen)
    cascades.touch_once(batch, seen)

    if derive.remaining_bbl(batch) <= calc.BATCH_CLOSE_REMAINDER_BBL:
        cascades.close_batch(batch, seen)
    return envelope.object_response(derive.serialize_run(run))


@bp.post("/packaging-runs/<run_id>/void")
def void_run(run_id):
    authenticate(["CellarOperator"])
    validation.body()
    run = helpers.find("runs", run_id)
    state = run.get("state")
    if state not in ("PLANNED", "COMPLETED"):
        raise ApiError("ERR_RUN_TRANSITION_INVALID")

    if state == "COMPLETED":
        if (derive.run_allocated_bbl(run) != 0
                or derive.run_shipped_bbl(run) != 0
                or (run.get("kegs_filled_count") or 0) != 0):
            raise ApiError("ERR_RUN_HAS_ALLOCATIONS")

    seen = set()
    if state == "PLANNED":
        run["state"] = "VOIDED"
        run["voided_at_utc"] = helpers.now()
        cascades.touch_once(run, seen)
        return envelope.object_response(derive.serialize_run(run))

    batch = helpers.find("batches", run["batch_id"])
    run["state"] = "VOIDED"
    run["bbl_removed"] = calc.bbl(0)
    run["units_produced"] = None
    run["loss_share_bbl"] = None
    run["voided_at_utc"] = helpers.now()
    cascades.touch_once(run, seen)
    cascades.touch_once(batch, seen)
    if batch.get("state") == "PACKAGED":
        if batch.get("actual_yield_bbl") is not None:
            batch["total_loss_bbl"] = calc.bbl(
                Decimal(batch["actual_yield_bbl"]) - derive.packaged_bbl(batch))
        cascades.allocate_packaging_loss(batch, seen)
    return envelope.object_response(derive.serialize_run(run))
