"""Region endpoints."""
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from validation import require_fields, require_number, get_or_404

bp = Blueprint("regions", __name__)

READ_ROLES = {"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator",
              "PolicyAnalyst", "ImageryOperator", "RoutingEngineer"}


@bp.post("/v1/regions")
def create_region():
    require_roles({"PlatformAdmin"})
    data = body()
    require_fields(data, ["name", "country_code", "timezone",
                          "geo_min_lat", "geo_max_lat", "geo_min_lng", "geo_max_lng"])
    cc = data["country_code"]
    if not isinstance(cc, str) or len(cc) != 2 or not cc.isalpha() or cc != cc.upper():
        raise_err("ERR_INVALID_REQUEST", "country_code must be 2 uppercase letters")
    min_lat = require_number(data, "geo_min_lat")
    max_lat = require_number(data, "geo_max_lat")
    min_lng = require_number(data, "geo_min_lng")
    max_lng = require_number(data, "geo_max_lng")
    max_tasks = data.get("max_active_imagery_tasks", 5)
    if not isinstance(max_tasks, int) or isinstance(max_tasks, bool) or max_tasks < 0:
        raise_err("ERR_INVALID_REQUEST", "max_active_imagery_tasks must be a non-negative integer")
    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "name": data["name"],
        "country_code": cc,
        "timezone": data["timezone"],
        "geo_min_lat": min_lat,
        "geo_max_lat": max_lat,
        "geo_min_lng": min_lng,
        "geo_max_lng": max_lng,
        "max_active_imagery_tasks": max_tasks,
        "posture": "ACTIVE",
        "privacy_pending_count": 0,
        "routing_version": 0,
        "frozen": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.regions[rec["id"]] = rec
    domain.recompute_region(rec)
    return envelope(domain.region_view(rec), status=201)


@bp.get("/v1/regions")
def list_regions():
    require_roles(READ_ROLES)
    posture = request.args.get("posture")
    items = [domain.recompute_region(r) for r in store.regions.values()]
    if posture is not None:
        items = [r for r in items if r["posture"] == posture]
    page, pg = paginate(items, request.args)
    return envelope([domain.region_view(r) for r in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/regions/<rid>")
def get_region(rid):
    require_roles(READ_ROLES)
    rg = get_or_404(store.regions, rid)
    return envelope(domain.region_view(rg))
