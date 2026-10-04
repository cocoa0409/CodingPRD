"""The operational-design-domain and curb corpus.

ServiceAreaRule rows gate route classes, ExclusionZone rows block them for a
closed time window, CurbRule rows bind a curb access class to a service type,
and PickupLocation rows carry the `is_valid` flag that reclassification flips.
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    FLEET_OPERATIONS,
    MAPPING_ENGINEER,
    REMOTE_ASSISTANCE_OPERATOR,
    SAFETY_REVIEWER,
    TERRITORY_PLANNER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_str,
    require_bool,
    require_enum,
    require_instant,
    require_int,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("area", __name__)

ROUTE_CLASSES = ("FREEWAY", "ARTERIAL", "RESIDENTIAL", "ALLEY")
ZONE_KINDS = ("CONSTRUCTION", "EVENT", "EMERGENCY", "WEATHER", "TEMPORARY")
CURB_ACCESS = ("SAFE", "NO_STOPPING", "LOADING_ONLY")
SUB_SERVICE_TYPES = ("STANDARD", "ASSISTED")


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


def _canonical(value):
    from db import format_utc

    return format_utc(calc._instant(value))


def _add_seconds(value, seconds):
    import datetime as dt

    return calc._instant(value) + dt.timedelta(seconds=seconds)


# ─── ServiceAreaRule ──────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/area-rules")
def create_area_rule(territory_id):
    _resolve((MAPPING_ENGINEER,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    rule = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "rule_version": 1,
        "route_class": require_enum(body, "route_class", ROUTE_CLASSES),
        "allowed": require_bool(body, "allowed"),
        "notes": body.get("notes"),
        "status": "DRAFT",
        "version": 1,
    }
    store.stamp_create(rule)
    store.area_rules[rule["id"]] = rule
    return success_object(rule, 201)


@bp.get("/fleet/territories/<territory_id>/area-rules")
def list_territory_area_rules(territory_id):
    _resolve((FLEET_OPERATIONS, MAPPING_ENGINEER, SAFETY_REVIEWER))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.area_rules.values() if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("status", "status"), ("route_class", "route_class")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/area-rules")
def list_area_rules():
    _resolve((ANY,))
    rows = list(store.area_rules.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("status", "status"), ("route_class", "route_class")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/area-rules/<rule_id>")
def get_area_rule(rule_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.area_rules, rule_id))


@bp.post("/fleet/territories/<territory_id>/area-rules/<rule_id>/approve")
def approve_area_rule(territory_id, rule_id):
    _resolve((SAFETY_REVIEWER,))
    get_or_404(store.territories, territory_id)
    rule = get_or_404(store.area_rules, rule_id)
    if rule["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if rule["status"] != "DRAFT":
        raise fail("ERR_INVALID_STATE")
    rule["status"] = "APPROVED"
    rule["rule_version"] = rule["rule_version"] + 1
    store.touch(rule)
    return success_object(rule)


@bp.post("/fleet/territories/<territory_id>/area-rules/<rule_id>/retire")
def retire_area_rule(territory_id, rule_id):
    _resolve((MAPPING_ENGINEER,))
    get_or_404(store.territories, territory_id)
    rule = get_or_404(store.area_rules, rule_id)
    if rule["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if rule["status"] != "APPROVED":
        raise fail("ERR_INVALID_STATE")
    rule["status"] = "RETIRED"
    store.touch(rule)
    return success_object(rule)


# ─── ExclusionZone ────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/exclusion-zones")
def create_exclusion_zone(territory_id):
    _resolve((SAFETY_REVIEWER, MAPPING_ENGINEER))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    start_utc = require_instant(body, "start_utc")
    duration_seconds = require_int(body, "duration_seconds", minimum=0)
    zone = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "kind": require_enum(body, "kind", ZONE_KINDS),
        "route_class": require_enum(body, "route_class", ROUTE_CLASSES),
        "start_utc": _canonical(start_utc),
        "duration_seconds": duration_seconds,
        "end_utc": _canonical(_add_seconds(start_utc, duration_seconds)),
        "status": "SCHEDULED",
        "version": 1,
    }
    store.stamp_create(zone)
    store.exclusion_zones[zone["id"]] = zone
    return success_object(zone, 201)


@bp.get("/fleet/territories/<territory_id>/exclusion-zones")
def list_territory_exclusion_zones(territory_id):
    _resolve((FLEET_OPERATIONS, MAPPING_ENGINEER, SAFETY_REVIEWER, TERRITORY_PLANNER))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.exclusion_zones.values() if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("status", "status"), ("route_class", "route_class")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/exclusion-zones")
def list_exclusion_zones():
    _resolve((ANY,))
    rows = list(store.exclusion_zones.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("status", "status"), ("route_class", "route_class")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/exclusion-zones/<zone_id>")
def get_exclusion_zone(zone_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.exclusion_zones, zone_id))


@bp.post("/fleet/territories/<territory_id>/exclusion-zones/<zone_id>/activate")
def activate_exclusion_zone(territory_id, zone_id):
    _resolve((SAFETY_REVIEWER,))
    territory = get_or_404(store.territories, territory_id)
    zone = get_or_404(store.exclusion_zones, zone_id)
    if zone["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if zone["status"] != "SCHEDULED":
        raise fail("ERR_INVALID_STATE")
    zone["status"] = "ACTIVE"
    store.touch(zone)
    # Activation changes the zone accumulator and can move the territory's
    # posture; both land on the same row, so the row advances exactly once.
    zone_count = calc.active_zone_count(territory_id)
    posture = calc.compute_territory_posture(territory)
    if territory["active_zone_count"] != zone_count or territory["posture"] != posture:
        territory["active_zone_count"] = zone_count
        territory["posture"] = posture
        store.touch(territory)
    return success_object(zone)


# ─── PickupLocation + CurbRule ────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/pickup-locations")
def create_pickup_location(territory_id):
    _resolve((MAPPING_ENGINEER,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    location = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "curb_segment_code": require_str(body, "curb_segment_code"),
        "curb_access": require_enum(body, "curb_access", CURB_ACCESS),
        "is_valid": True,
        "version": 1,
    }
    store.stamp_create(location)
    store.pickup_locations[location["id"]] = location
    return success_object(location, 201)


@bp.get("/fleet/territories/<territory_id>/pickup-locations")
def list_territory_pickup_locations(territory_id):
    _resolve((FLEET_OPERATIONS, MAPPING_ENGINEER, REMOTE_ASSISTANCE_OPERATOR))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.pickup_locations.values() if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("curb_access", "curb_access"), ("is_valid", "is_valid")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/pickup-locations")
def list_pickup_locations():
    _resolve((ANY,))
    rows = list(store.pickup_locations.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("curb_access", "curb_access"), ("is_valid", "is_valid")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/pickup-locations/<pickup_location_id>")
def get_pickup_location(pickup_location_id):
    _resolve((FLEET_OPERATIONS, MAPPING_ENGINEER, REMOTE_ASSISTANCE_OPERATOR))
    return success_object(get_or_404(store.pickup_locations, pickup_location_id))


@bp.get("/fleet/pickup-locations/<pickup_location_id>/ride-requests")
def list_pickup_location_rides(pickup_location_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR))
    get_or_404(store.pickup_locations, pickup_location_id)
    rows = [
        row
        for row in store.rides.values()
        if row.get("pickup_location_id") == pickup_location_id
        or row.get("dropoff_location_id") == pickup_location_id
    ]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.post("/fleet/pickup-locations/<pickup_location_id>/reclassify")
def reclassify_pickup_location(pickup_location_id):
    _resolve((MAPPING_ENGINEER,))
    location = get_or_404(store.pickup_locations, pickup_location_id)
    body = body_object(request.get_json(silent=True))
    curb_access = require_enum(body, "curb_access", CURB_ACCESS)
    location["curb_access"] = curb_access
    location["is_valid"] = curb_access != "NO_STOPPING"
    store.touch(location)
    return success_object(location)


@bp.post("/fleet/territories/<territory_id>/curb-rules")
def create_curb_rule(territory_id):
    _resolve((SAFETY_REVIEWER,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    rule = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "curb_access": require_enum(body, "curb_access", CURB_ACCESS),
        "sub_service_type": require_enum(body, "sub_service_type", SUB_SERVICE_TYPES),
        "allowed": require_bool(body, "allowed"),
        "status": "ACTIVE",
        "version": 1,
    }
    store.stamp_create(rule)
    store.curb_rules[rule["id"]] = rule
    return success_object(rule, 201)


@bp.get("/fleet/territories/<territory_id>/curb-rules")
def list_territory_curb_rules(territory_id):
    _resolve((FLEET_OPERATIONS, SAFETY_REVIEWER, MAPPING_ENGINEER))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.curb_rules.values() if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("status", "status"), ("sub_service_type", "sub_service_type")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/curb-rules")
def list_curb_rules():
    _resolve((ANY,))
    rows = list(store.curb_rules.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args, (("status", "status"), ("sub_service_type", "sub_service_type")))
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/curb-rules/<curb_rule_id>")
def get_curb_rule(curb_rule_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.curb_rules, curb_rule_id))


@bp.post("/fleet/territories/<territory_id>/curb-rules/<curb_rule_id>/retire")
def retire_curb_rule(territory_id, curb_rule_id):
    _resolve((SAFETY_REVIEWER,))
    get_or_404(store.territories, territory_id)
    rule = get_or_404(store.curb_rules, curb_rule_id)
    if rule["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if rule["status"] != "ACTIVE":
        raise fail("ERR_INVALID_STATE")
    rule["status"] = "RETIRED"
    store.touch(rule)
    return success_object(rule)


# ─── shared filter helper ─────────────────────────────────────────────────


def _filter(rows, params, mapping):
    for param, field in mapping:
        raw = params.get(param)
        if raw is None or raw == "":
            continue
        if str(raw).lower() in ("true", "false"):
            wanted = str(raw).lower() == "true"
        else:
            wanted = raw
        rows = [row for row in rows if row.get(field) == wanted]
    return rows