"""Blood collection continuity and the logical-clock administration endpoint."""

import calc
import core
from core import (authenticate, base_row, clock, find, insert, list_response,
                  must_get, ok_object, parse_instant, read_json, rows, serialize,
                  touch, validate_body)
from errors import ApiError
from flask import Blueprint, request

bp = Blueprint("blood", __name__)

BLOOD_ROLES = ["NationalHQAdmin", "BloodServicesCoordinator"]
BLOOD_READ_ROLES = ["NationalHQAdmin", "BloodServicesCoordinator", "RegionalCoordinator"]


@bp.post("/api/v1/blood-drives")
def create_blood_drive():
    authenticate(BLOOD_ROLES)
    body = read_json()
    validate_body(body, required={
        "region_id": str,
        "site_name": str,
        "scheduled_start_at": "instant",
        "scheduled_end_at": "instant",
        "target_units": int,
    })
    region = must_get("regions", body["region_id"])
    if body["target_units"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_units must be >= 1")
    start = parse_instant(body["scheduled_start_at"])
    end = parse_instant(body["scheduled_end_at"])
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_end_at must be strictly after scheduled_start_at")
    for drive in rows("blood_drives"):
        if drive["status"] == "CANCELLED" or drive["site_name"] != body["site_name"]:
            continue
        other_start = parse_instant(drive["scheduled_start_at"])
        other_end = parse_instant(drive["scheduled_end_at"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_BLOOD_DRIVE_WINDOW_OVERLAP", 409,
                           "another drive already holds this window at the site")
    record = base_row()
    record.update({
        "region_id": region["id"],
        "site_name": body["site_name"],
        "scheduled_start_at": core.iso_of(body["scheduled_start_at"]),
        "scheduled_end_at": core.iso_of(body["scheduled_end_at"]),
        "target_units": body["target_units"],
        "collected_units": 0,
        "usable_units": 0,
        "status": "PLANNED",
    })
    insert("blood_drives", record)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/blood-drives/<drive_id>/collections")
def record_collection(drive_id):
    authenticate(BLOOD_ROLES)
    body = read_json()
    validate_body(body, required={"units": int})
    drive = must_get("blood_drives", drive_id)
    if drive["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the blood drive is terminal")
    if drive["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "the drive is not collecting")
    if body["units"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "units must be >= 1")
    if int(drive["collected_units"]) + body["units"] > int(drive["target_units"]):
        raise ApiError("ERR_COLLECTION_TARGET_EXCEEDED", 409,
                       "the collection would exceed the drive target")
    drive["collected_units"] = int(drive["collected_units"]) + body["units"]
    drive["usable_units"] = calc.usable_units(drive["collected_units"])
    touch(drive)
    return ok_object(serialize(drive))


@bp.post("/api/v1/blood-drives/<drive_id>/cancel")
def cancel_blood_drive(drive_id):
    authenticate(BLOOD_ROLES)
    validate_body(read_json(), required={})
    drive = must_get("blood_drives", drive_id)
    if drive["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the blood drive is terminal")
    if drive["status"] == "PLANNED" and int(drive["collected_units"]) != 0:
        raise ApiError("ERR_INVALID_STATE", 409, "a planned drive with collections cannot be cancelled")
    drive["status"] = "CANCELLED"
    touch(drive)
    region = find("regions", drive["region_id"])
    if region is not None:
        calc.refresh_region(region)
    return ok_object(serialize(drive))


@bp.get("/api/v1/blood-drives/<drive_id>")
def read_blood_drive(drive_id):
    authenticate(BLOOD_READ_ROLES)
    return ok_object(serialize(must_get("blood_drives", drive_id)))


@bp.get("/api/v1/blood-drives")
def list_blood_drives():
    authenticate(BLOOD_READ_ROLES)
    drives = rows("blood_drives")
    region_id = request.args.get("region_id")
    if region_id:
        drives = [d for d in drives if d["region_id"] == region_id]
    return list_response(drives)


# ------------------------------------------------------------- logical clock


@bp.post("/api/v1/_clock/set_current_utc")
def set_current_utc():
    # PRD 2.1 exempts the clock administration capability from the
    # header-presence requirement; the role check still applies when a role
    # header is supplied.
    authenticate(["NationalHQAdmin"], headers_optional=True)
    body = read_json()
    validate_body(body, required={"to_iso8601": "instant"})
    clock.set(parse_instant(body["to_iso8601"]))
    return ok_object({"to_iso8601": core.iso_of(body["to_iso8601"])})
