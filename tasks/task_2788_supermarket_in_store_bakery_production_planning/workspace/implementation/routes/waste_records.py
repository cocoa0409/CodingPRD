"""Waste record endpoints: attestation and the void reversal (PRD 3.6)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    DISPOSITION_REASONS,
    RECORD_STATUSES,
    as_enum,
    as_int,
    as_string,
    authenticate,
    body,
    enum_filter,
    find_run,
    find_waste_record,
    scope,
)
from response import created, listing, ok, parse_pagination, touch
from services.rollups import recompute_bake_day
from services.runs import attest_waste, recompute_run_shelf
from store import by_seq, db

bp = Blueprint("waste_records", __name__)


@bp.post("/bakery/waste-records")
def create_waste_record():
    caller = authenticate(("Baker", "DepartmentManager"))
    payload = body()
    run = find_run(payload.get("production_run_id"))
    day = db.bake_days.get(run["bake_day_id"])
    scope(caller, day["department_id"] if day else None)

    reason = as_enum(payload, "disposition_reason", DISPOSITION_REASONS)
    units = as_int(payload, "units", minimum=1)

    if day is not None and day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")
    if run["execution_status"] != "COMPLETED":
        raise ApiError("ERR_RUN_NOT_COMPLETED")

    if run["executed_by_user_id"] is not None and run["executed_by_user_id"] == caller.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if units > int(run["on_shelf_units"] or 0):
        raise ApiError("ERR_WASTE_EXCEEDS_ON_SHELF")

    record = attest_waste(run, reason, units, caller.user_id)
    return created(serializers.waste_record(record))


@bp.get("/bakery/waste-records/<wasteRecordId>")
def read_waste_record(wasteRecordId):
    authenticate(ANY_ROLE)
    return ok(serializers.waste_record(find_waste_record(wasteRecordId)))


@bp.get("/bakery/waste-records")
def list_waste_records():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    bake_day_id = request.args.get("bake_day_id") or None
    production_run_id = request.args.get("production_run_id") or None
    reason = enum_filter(request.args, "disposition_reason", DISPOSITION_REASONS)
    status = enum_filter(request.args, "record_status", RECORD_STATUSES)
    rows = []
    for row in db.waste_records.values():
        if bake_day_id is not None and row["bake_day_id"] != bake_day_id:
            continue
        if production_run_id is not None and row["production_run_id"] != production_run_id:
            continue
        if reason is not None and row["disposition_reason"] != reason:
            continue
        if status is not None and row["record_status"] != status:
            continue
        rows.append(row)
    return listing([serializers.waste_record(row) for row in by_seq(rows)], limit, offset)


@bp.post("/bakery/waste-records/<wasteRecordId>/void")
def void_waste_record(wasteRecordId):
    caller = authenticate(("DepartmentManager",))
    record = find_waste_record(wasteRecordId)
    day = db.bake_days.get(record["bake_day_id"])
    scope(caller, day["department_id"] if day else None)
    payload = body()
    void_reason = as_string(payload, "void_reason", min_len=1, max_len=500)

    if day is not None and day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")
    if record["record_status"] != "ACTIVE":
        raise ApiError("ERR_WASTE_RECORD_ALREADY_VOIDED")

    record["record_status"] = "VOIDED"
    record["void_reason"] = void_reason
    record["voided_by_user_id"] = caller.user_id
    touch(record)

    run = db.runs.get(record["production_run_id"])
    if run is not None:
        recompute_run_shelf(run)
    if day is not None:
        recompute_bake_day(day)
    return ok(serializers.waste_record(record))
