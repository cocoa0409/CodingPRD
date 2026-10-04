"""Carhop endpoints (PRD 3.6)."""
from db import db
from errors import invalid_request
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_int,
    get_enum,
    get_bool,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import carhop as ser_carhop
from services import make_record, get_location, get_carhop_nested
from . import carhops_bp

ZONES = ["NORTH", "SOUTH", "PATIO"]
ROLES = ["ShiftManager", "Carhop", "PlatformAdmin"]


@carhops_bp.route("/locations/<locationId>/carhops", methods=["POST"])
def create_carhop(locationId):
    require_auth(["ShiftManager", "PlatformAdmin"])
    loc = get_location(locationId)
    body = body_json()
    name = get_str(body, "name", required=True)
    zone = get_enum(body, "zone", ZONES, required=True)
    on_shift = get_bool(body, "on_shift", default=True)
    max_trays = get_int(body, "max_trays", default=3, minimum=1)
    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "name": name,
            "zone": zone,
            "on_shift": on_shift,
            "max_trays": max_trays,
            "active_run_load": 0,
            "tips_outstanding_cents": 0,
            "tips_settled_cents": 0,
        }
    )
    db.carhops[rec["id"]] = rec
    return success_object(ser_carhop(rec), 201)


@carhops_bp.route("/locations/<locationId>/carhops", methods=["GET"])
def list_carhops(locationId):
    require_auth(ROLES)
    from flask import request

    get_location(locationId)
    zone = request.args.get("zone")
    on_shift_raw = request.args.get("on_shift")
    if zone is not None and zone not in ZONES:
        invalid_request("zone must be NORTH, SOUTH, or PATIO")
    carhops = [c for c in db.carhops.values() if c["location_id"] == locationId]
    if zone is not None:
        carhops = [c for c in carhops if c["zone"] == zone]
    if on_shift_raw is not None:
        if on_shift_raw not in ("true", "false"):
            invalid_request("on_shift must be true or false")
        want = on_shift_raw == "true"
        carhops = [c for c in carhops if c["on_shift"] == want]
    carhops = sort_by_created(carhops)
    limit, offset = pagination_params()
    total = len(carhops)
    page = carhops[offset : offset + limit]
    return success_array([ser_carhop(c) for c in page], limit, offset, total)


@carhops_bp.route("/locations/<locationId>/carhops/<carhopId>", methods=["GET"])
def get_carhop(locationId, carhopId):
    require_auth(ROLES)
    loc, carhop = get_carhop_nested(locationId, carhopId)
    return success_object(ser_carhop(carhop))
