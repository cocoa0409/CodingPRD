"""Drive units blueprint."""

from flask import Blueprint, request

import errors
from cascades import entity_out, list_out
from db import store
from middleware import require_roles
from models import base_entity, bump, get_or_404, req_str, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("drive_units", __name__)

READ_ROLES = {"FleetAdmin", "FlowController", "MaintenanceTech", "FloorSupervisor"}
TERMINAL_TASK_STATUSES = {"COMPLETE", "FAILED", "CANCELLED"}


@bp.route("/drive-units", methods=["POST"])
def create_drive_unit():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    unit_code = req_str(body, "unit_code")
    home_zone_id = require_field(body, "home_zone_id")
    if not isinstance(home_zone_id, str):
        raise errors.validation("home_zone_id must be a string")
    get_or_404(store.zones, home_zone_id, "zone")
    for u in store.drive_units.values():
        if u["unit_code"] == unit_code:
            raise errors.validation(f"unit_code already exists: {unit_code}")
    unit = base_entity()
    unit.update(
        {
            "unit_code": unit_code,
            "status": "ACTIVE",
            "home_zone_id": home_zone_id,
            "battery_pct": 100,
            "firmware_release_id": None,
            "odometer_cells": 0,
            "charge_cycle_count": 0,
        }
    )
    store.drive_units[unit["id"]] = unit
    return success_object(entity_out(unit), status=201)


@bp.route("/drive-units", methods=["GET"])
def list_drive_units():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    home_zone_f = request.args.get("home_zone_id")
    firmware_f = request.args.get("firmware_release_id")
    items = list(store.drive_units.values())
    if status_f is not None:
        items = [u for u in items if u["status"] == status_f]
    if home_zone_f is not None:
        items = [u for u in items if u["home_zone_id"] == home_zone_f]
    if firmware_f is not None:
        items = [u for u in items if u.get("firmware_release_id") == firmware_f]
    items.sort(key=lambda u: u["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/drive-units/<unit_id>", methods=["GET"])
def get_drive_unit(unit_id):
    require_roles(READ_ROLES)
    unit = get_or_404(store.drive_units, unit_id, "drive unit")
    return success_object(entity_out(unit))


@bp.route("/drive-units/<unit_id>/retire", methods=["POST"])
def retire_drive_unit(unit_id):
    require_roles({"FleetAdmin"})
    unit = get_or_404(store.drive_units, unit_id, "drive unit")
    if unit["status"] != "ACTIVE":
        raise errors.invalid_state("drive unit is not ACTIVE")
    for task in store.pick_tasks.values():
        if task.get("drive_unit_id") == unit_id and task["status"] not in TERMINAL_TASK_STATUSES:
            raise errors.invalid_state("drive unit referenced by non-terminal pick task")
    unit["status"] = "RETIRED"
    bump(unit)
    return success_object(entity_out(unit))
