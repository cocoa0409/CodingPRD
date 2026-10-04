"""Factory endpoints (PRD 3.1): create, list, get, suspend, reactivate."""
from flask import Blueprint, request

import cascade
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_enum, req_int, opt_bool

bp = Blueprint("factories", __name__)


def get_factory(fid):
    f = DB["factories"].get(fid)
    if f is None:
        raise ApiError("ERR_FACTORY_NOT_FOUND", "factory id does not resolve")
    return f


@bp.post("/footwear/factories")
@require_roles("PlatformAdmin")
def create_factory(_uid, _role):
    b = body()
    name = req_str(b, "factory_name")
    loc = req_enum(b, "location_type", constants.LOCATION_TYPES)
    gov = opt_bool(b, "government_cleared", False)
    cap = req_int(b, "weekly_capacity_units", min_v=1)
    lines = req_int(b, "line_count", min_v=1)
    rate = req_int(b, "labor_rate_cents_per_minute", min_v=0)
    ovh = req_int(b, "overhead_cents_per_pair", min_v=0)
    f = base_fields()
    f.update({
        "factory_name": name,
        "location_type": loc,
        "government_cleared": gov,
        "weekly_capacity_units": cap,
        "line_count": lines,
        "labor_rate_cents_per_minute": rate,
        "overhead_cents_per_pair": ovh,
        "status": "ACTIVE",
    })
    DB["factories"][f["id"]] = f
    return ok_obj(serializers.factory(f), 201)


@bp.get("/footwear/factories")
@require_roles(*constants.ALL_ROLES)
def list_factories(_uid, _role):
    items = sorted_items(DB["factories"])
    status = request.args.get("status")
    loc = request.args.get("location_type")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if loc is not None:
        items = [f for f in items if f["location_type"] == loc]
    return list_response([serializers.factory(f) for f in items])


@bp.get("/footwear/factories/<fid>")
@require_roles(*constants.ALL_ROLES)
def get_one_factory(fid, _uid, _role):
    return ok_obj(serializers.factory(get_factory(fid)))


@bp.post("/footwear/factories/<fid>/suspend")
@require_roles("PlatformAdmin")
def suspend_factory(fid, _uid, _role):
    f = get_factory(fid)
    if f["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE factory can be suspended")
    f["status"] = "SUSPENDED"
    touch(f)
    cascade.cascade_factory_suspend(f)
    return ok_obj(serializers.factory(f))


@bp.post("/footwear/factories/<fid>/reactivate")
@require_roles("PlatformAdmin")
def reactivate_factory(fid, _uid, _role):
    f = get_factory(fid)
    if f["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "only a SUSPENDED factory can be reactivated")
    f["status"] = "ACTIVE"
    touch(f)
    return ok_obj(serializers.factory(f))
