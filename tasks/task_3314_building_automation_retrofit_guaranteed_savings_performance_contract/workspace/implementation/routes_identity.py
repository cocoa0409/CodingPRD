"""Logical clock and identity actor routes."""
from flask import Blueprint, request

import db
from errors import ApiError, ok
from util import body, new_id, now_iso, parse_dt, req_string, require_roles

bp = Blueprint("identity", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    data = body()
    current = data.get("current_utc")
    if not isinstance(current, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "current_utc is required")
    dt = parse_dt(current, "current_utc")
    db.set_logical_now(dt)
    stamp = dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return ok({"current_utc": stamp})


@bp.route("/owner-reps", methods=["POST"])
def create_owner_rep():
    require_roles("PlatformAdmin")
    data = body()
    rec = {
        "id": new_id(),
        "full_name": req_string(data, "full_name"),
        "organization": req_string(data, "organization"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.owner_reps[rec["id"]] = rec
    return ok(dict(rec), code=201)


@bp.route("/owner-reps/<ownerRepId>", methods=["GET"])
def get_owner_rep(ownerRepId):
    require_roles()
    rec = db.owner_reps.get(ownerRepId)
    if rec is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 404, "owner rep not found")
    return ok(dict(rec))


@bp.route("/esco-engineers", methods=["POST"])
def create_engineer():
    require_roles("PlatformAdmin")
    data = body()
    rec = {
        "id": new_id(),
        "full_name": req_string(data, "full_name"),
        "license_number": req_string(data, "license_number"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.engineers[rec["id"]] = rec
    return ok(dict(rec), code=201)


@bp.route("/esco-engineers/<engineerId>", methods=["GET"])
def get_engineer(engineerId):
    require_roles()
    rec = db.engineers.get(engineerId)
    if rec is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 404, "ESCO engineer not found")
    return ok(dict(rec))
