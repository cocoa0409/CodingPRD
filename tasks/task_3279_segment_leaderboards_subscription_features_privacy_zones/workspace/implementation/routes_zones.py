"""Privacy zone routes with OCC on owning athlete."""
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_unique, err_forbidden,
                    err_stale_version)
from middleware import require_roles, check_self_or_admin
from response import ok_object, ok_list, init_common, touch, parse_pagination
from serializers import zone_view
from services import recompute_obfuscation

bp = Blueprint("privacy_zones", __name__)


def _validate_geo(lat, lng, radius):
    if not isinstance(lat, (int, float)) or isinstance(lat, bool) or not (-90 <= lat <= 90):
        raise err_validation("center_lat must be -90..90")
    if not isinstance(lng, (int, float)) or isinstance(lng, bool) or not (-180 <= lng <= 180):
        raise err_validation("center_lng must be -180..180")
    if not isinstance(radius, int) or isinstance(radius, bool) or not (200 <= radius <= 2000):
        raise err_validation("radius_m must be integer 200..2000")


def _reobfuscate_owner(athlete_id):
    for act in db.activities.values():
        if act["athlete_id"] == athlete_id:
            recompute_obfuscation(act)
            touch(act)


@bp.post("/v1/athletes/<aid>/privacy_zones")
def create_zone(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    a = db.athletes.get(aid)
    if not a:
        raise err_not_found("Athlete not found")
    check_self_or_admin(user_id, role, aid)
    body = request.get_json(silent=True) or {}
    lat = body.get("center_lat"); lng = body.get("center_lng"); radius = body.get("radius_m")
    _validate_geo(lat, lng, radius)
    # one zone per athlete
    for z in db.privacy_zones.values():
        if z["athlete_id"] == aid:
            raise err_unique("one privacy zone per athlete")
    zone = init_common({
        "athlete_id": aid,
        "center_lat": lat,
        "center_lng": lng,
        "radius_m": radius,
        "status": "ACTIVE",
    })
    db.privacy_zones[zone["id"]] = zone
    _reobfuscate_owner(aid)
    return ok_object(zone_view(zone), 201)


@bp.get("/v1/athletes/<aid>/privacy_zones")
def list_zones(aid):
    require_roles("Athlete", "PlatformAdmin")
    a = db.athletes.get(aid)
    if not a:
        raise err_not_found("Athlete not found")
    items = [z for z in db.privacy_zones.values() if z["athlete_id"] == aid]
    items.sort(key=lambda z: z["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([zone_view(z) for z in items], limit, offset)


def _get_zone_or_404(zid):
    z = db.privacy_zones.get(zid)
    if not z:
        raise err_not_found("Privacy zone not found")
    return z


@bp.get("/v1/privacy-zones/<zid>")
def get_zone(zid):
    require_roles("Athlete", "PlatformAdmin")
    z = _get_zone_or_404(zid)
    return ok_object(zone_view(z))


@bp.put("/v1/privacy-zones/<zid>")
def update_zone(zid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    z = _get_zone_or_404(zid)
    check_self_or_admin(user_id, role, z["athlete_id"])
    body = request.get_json(silent=True) or {}
    lat = body.get("center_lat"); lng = body.get("center_lng"); radius = body.get("radius_m")
    expected = body.get("expected_athlete_version")
    _validate_geo(lat, lng, radius)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_validation("expected_athlete_version is required")
    athlete = db.athletes.get(z["athlete_id"])
    if not athlete:
        raise err_not_found("Athlete not found")
    if int(athlete.get("version", 0)) != expected:
        raise err_stale_version()
    z["center_lat"] = lat
    z["center_lng"] = lng
    z["radius_m"] = radius
    touch(z)
    # increment athlete version by 1 (cascading write on athlete aggregate)
    touch(athlete)
    _reobfuscate_owner(z["athlete_id"])
    return ok_object(zone_view(z))


@bp.post("/v1/privacy-zones/<zid>/disable")
def disable_zone(zid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    z = _get_zone_or_404(zid)
    check_self_or_admin(user_id, role, z["athlete_id"])
    z["status"] = "DISABLED"
    touch(z)
    _reobfuscate_owner(z["athlete_id"])
    return ok_object(zone_view(z))


@bp.post("/v1/privacy-zones/<zid>/enable")
def enable_zone(zid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    z = _get_zone_or_404(zid)
    check_self_or_admin(user_id, role, z["athlete_id"])
    z["status"] = "ACTIVE"
    touch(z)
    _reobfuscate_owner(z["athlete_id"])
    return ok_object(zone_view(z))
