"""Region endpoints."""
from flask import Blueprint

import db
from errors import err_duplicate, err_not_found, err_invalid_request
from response import (
    body, get_auth, require_roles, success_obj, paginate,
    req_string, req_number,
)

bp = Blueprint("regions", __name__)

ALL = ["PlatformAdmin", "RegionManager", "ChannelDirector", "ColorLabAdmin", "EquipmentTech", "DealerPrincipal"]


def serialize(r):
    return dict(r)


@bp.post("/regions")
def create_region():
    _, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    data = body()
    code = req_string(data, "code")
    name = req_string(data, "name")
    radius = req_number(data, "territory_radius_miles")
    threshold = req_number(data, "exclusivity_block_threshold_pct")
    if radius <= 0:
        raise err_invalid_request("territory_radius_miles must be > 0")
    if threshold < 0 or threshold > 100:
        raise err_invalid_request("exclusivity_block_threshold_pct must be in [0, 100]")
    for r in db.regions.values():
        if r["code"] == code:
            raise err_duplicate("region code already exists")
    rec = db.new_common()
    rec.update({
        "code": code,
        "name": name,
        "territory_radius_miles": radius,
        "exclusivity_block_threshold_pct": threshold,
        "active_dealer_count": 0,
        "pending_application_count": 0,
    })
    db.regions[rec["id"]] = rec
    return success_obj(serialize(rec), 201)


@bp.get("/regions")
def list_regions():
    get_auth()
    return paginate([serialize(r) for r in db.regions.values()])


@bp.get("/regions/<rid>")
def get_region(rid):
    get_auth()
    r = db.regions.get(rid)
    if r is None:
        raise err_not_found("region not found")
    return success_obj(serialize(r))
