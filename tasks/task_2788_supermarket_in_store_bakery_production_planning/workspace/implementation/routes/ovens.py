"""Oven endpoints and the availability cycle (PRD 3.1)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ALLERGEN_MODES,
    ANY_ROLE,
    OVEN_STATUSES,
    as_enum,
    as_int,
    as_string,
    authenticate,
    body,
    enum_filter,
    find_department,
    find_oven,
    scope,
)
from response import created, listing, mark_new, ok, parse_pagination, touch
from store import by_seq, db, new_entity

bp = Blueprint("ovens", __name__)


@bp.post("/bakery/ovens")
def create_oven():
    authenticate(("RegionalAdmin",))
    payload = body()
    department = find_department(payload.get("department_id"))

    name = as_string(payload, "name", min_len=1, max_len=60)
    deck_count = as_int(payload, "deck_count", minimum=1, maximum=8)
    rack_capacity = as_int(payload, "rack_capacity_per_deck", minimum=1, maximum=20)
    buffer_minutes = as_int(payload, "changeover_buffer_minutes", required=False, minimum=0, maximum=120,
                            default=0)
    allergen_mode = as_enum(payload, "allergen_mode", ALLERGEN_MODES, required=False, default="SHARED")

    for existing in db.ovens.values():
        if existing["department_id"] == department["id"] and existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_SKU", "name already exists in this department.")

    row = new_entity(
        department_id=department["id"],
        name=name,
        deck_count=deck_count,
        rack_capacity_per_deck=rack_capacity,
        changeover_buffer_minutes=buffer_minutes,
        allergen_mode=allergen_mode,
        oven_status="AVAILABLE",
        status_reason=None,
    )
    db.ovens[row["id"]] = row
    mark_new(row)
    return created(serializers.oven(row))


@bp.get("/bakery/ovens/<ovenId>")
def read_oven(ovenId):
    authenticate(ANY_ROLE)
    return ok(serializers.oven(find_oven(ovenId)))


@bp.get("/bakery/ovens")
def list_ovens():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    department_id = request.args.get("department_id") or None
    status = enum_filter(request.args, "oven_status", OVEN_STATUSES)
    mode = enum_filter(request.args, "allergen_mode", ALLERGEN_MODES)
    rows = []
    for row in db.ovens.values():
        if department_id is not None and row["department_id"] != department_id:
            continue
        if status is not None and row["oven_status"] != status:
            continue
        if mode is not None and row["allergen_mode"] != mode:
            continue
        rows.append(row)
    return listing([serializers.oven(row) for row in by_seq(rows)], limit, offset)


@bp.post("/bakery/ovens/<ovenId>/status")
def set_oven_status(ovenId):
    caller = authenticate(("DepartmentManager",))
    oven = find_oven(ovenId)
    scope(caller, oven["department_id"])
    payload = body()
    desired = as_enum(payload, "oven_status", OVEN_STATUSES)
    reason = as_string(payload, "status_reason", required=False, min_len=None, max_len=500, default=None)

    if desired == oven["oven_status"]:
        raise ApiError("ERR_INVALID_RUN_STATE", "The oven already reads %s." % desired)
    if oven["oven_status"] == "AVAILABLE" and desired == "MAINTENANCE":
        for run in db.runs.values():
            if run.get("oven_id") == oven["id"] and run["execution_status"] in ("PROOFING", "BAKING"):
                raise ApiError("ERR_INVALID_RUN_STATE", "A run is loaded on this oven.")

    oven["oven_status"] = desired
    oven["status_reason"] = reason
    touch(oven)
    return ok(serializers.oven(oven))
