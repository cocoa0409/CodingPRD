"""Zones blueprint."""

from flask import Blueprint, request

import errors
from cascades import entity_out, list_out
from db import store
from middleware import require_roles
from models import base_entity, get_or_404, req_int, req_str
from response import parse_pagination, success_list, success_object

bp = Blueprint("zones", __name__)

ALL_ROLES = {
    "FleetAdmin",
    "FlowController",
    "StationOperator",
    "FloorSupervisor",
    "SafetyOfficer",
    "MaintenanceTech",
    "ReleaseEngineer",
}


@bp.route("/zones", methods=["POST"])
def create_zone():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    zone_code = req_str(body, "zone_code")
    grid_x = req_int(body, "grid_x", minimum=0)
    grid_y = req_int(body, "grid_y", minimum=0)
    width = req_int(body, "width", minimum=1)
    height = req_int(body, "height", minimum=1)
    max_human_occupancy = req_int(body, "max_human_occupancy", minimum=1)
    for z in store.zones.values():
        if z["zone_code"] == zone_code:
            raise errors.validation(f"zone_code already exists: {zone_code}")
    zone = base_entity()
    zone.update(
        {
            "zone_code": zone_code,
            "grid_x": grid_x,
            "grid_y": grid_y,
            "width": width,
            "height": height,
            "posture": "OPEN",
            "max_human_occupancy": max_human_occupancy,
        }
    )
    store.zones[zone["id"]] = zone
    return success_object(entity_out(zone), status=201)


@bp.route("/zones", methods=["GET"])
def list_zones():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    zones = sorted(store.zones.values(), key=lambda z: z["created_at"])
    total = len(zones)
    page = zones[offset : offset + limit]
    return success_list(list_out(page), limit, offset, total)


@bp.route("/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    require_roles(ALL_ROLES)
    zone = get_or_404(store.zones, zone_id, "zone")
    return success_object(entity_out(zone))


@bp.route("/zones/<zone_id>/chargers", methods=["GET"])
def zone_chargers(zone_id):
    require_roles({"FleetAdmin", "FlowController", "MaintenanceTech"})
    get_or_404(store.zones, zone_id, "zone")
    limit, offset = parse_pagination()
    items = sorted(
        (c for c in store.chargers.values() if c["zone_id"] == zone_id),
        key=lambda c: c["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/zones/<zone_id>/pods", methods=["GET"])
def zone_pods(zone_id):
    require_roles({"FleetAdmin", "FlowController", "FloorSupervisor", "StationOperator"})
    get_or_404(store.zones, zone_id, "zone")
    limit, offset = parse_pagination()
    items = sorted(
        (p for p in store.pods.values() if p["zone_id"] == zone_id),
        key=lambda p: p["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/zones/<zone_id>/pick-stations", methods=["GET"])
def zone_stations(zone_id):
    require_roles({"FleetAdmin", "FlowController", "StationOperator"})
    get_or_404(store.zones, zone_id, "zone")
    limit, offset = parse_pagination()
    items = sorted(
        (s for s in store.pick_stations.values() if s["zone_id"] == zone_id),
        key=lambda s: s["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/zones/<zone_id>/human-entry-permits", methods=["GET"])
def zone_permits(zone_id):
    require_roles({"FleetAdmin", "FloorSupervisor", "SafetyOfficer"})
    get_or_404(store.zones, zone_id, "zone")
    limit, offset = parse_pagination()
    items = sorted(
        (p for p in store.human_entry_permits.values() if p["zone_id"] == zone_id),
        key=lambda p: p["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)
