"""Maintenance windows blueprint."""

from datetime import timedelta

from flask import Blueprint, request

import errors
from cascades import _activate_window, entity_out, list_out
from db import store
from middleware import require_roles
from models import (
    base_entity,
    bump,
    fmt_iso,
    get_or_404,
    parse_iso,
    req_enum,
    require_field,
)
from response import parse_pagination, success_list, success_object

bp = Blueprint("maintenance_windows", __name__)

READ_ROLES = {"FleetAdmin", "MaintenanceTech", "FlowController"}
BUFFER = timedelta(minutes=15)


@bp.route("/maintenance-windows", methods=["POST"])
def create_window():
    require_roles({"MaintenanceTech"})
    body = request.get_json(silent=True) or {}
    drive_unit_id = require_field(body, "drive_unit_id")
    if not isinstance(drive_unit_id, str):
        raise errors.validation("drive_unit_id must be a string")
    get_or_404(store.drive_units, drive_unit_id, "drive unit")
    starts_raw = require_field(body, "starts_at")
    ends_raw = require_field(body, "ends_at")
    starts_dt = parse_iso(starts_raw, "starts_at")
    ends_dt = parse_iso(ends_raw, "ends_at")
    kind = req_enum(body, "kind", {"PREVENTIVE", "CORRECTIVE"})
    # Half-open shape: ends_at strictly greater than starts_at.
    if ends_dt <= starts_dt:
        raise errors.temporal_conflict("ends_at must be strictly greater than starts_at")
    # 15-minute gap to any existing non-cancelled window for the same unit
    # (half-open semantics; exactly 15 minutes is allowed).
    for w in store.maintenance_windows.values():
        if w["drive_unit_id"] != drive_unit_id:
            continue
        if w["status"] == "CANCELLED":
            continue
        ws = w["_starts_dt"]
        we = w["_ends_dt"]
        if not (starts_dt >= we + BUFFER or ends_dt <= ws - BUFFER):
            raise errors.temporal_conflict(
                "window violates 15-minute gap to existing window"
            )
    window = base_entity()
    window.update(
        {
            "drive_unit_id": drive_unit_id,
            "starts_at": fmt_iso(starts_dt),
            "ends_at": fmt_iso(ends_dt),
            "status": "SCHEDULED",
            "kind": kind,
            "_starts_dt": starts_dt,
            "_ends_dt": ends_dt,
        }
    )
    store.maintenance_windows[window["id"]] = window
    # If current clock already inside the half-open interval, activate immediately.
    if window["_starts_dt"] <= store.clock < window["_ends_dt"]:
        _activate_window(window)
    return success_object(entity_out(window), status=201)


@bp.route("/maintenance-windows", methods=["GET"])
def list_windows():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.maintenance_windows.values())
    unit_f = request.args.get("drive_unit_id")
    status_f = request.args.get("status")
    if unit_f is not None:
        items = [w for w in items if w["drive_unit_id"] == unit_f]
    if status_f is not None:
        items = [w for w in items if w["status"] == status_f]
    items.sort(key=lambda w: w["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/maintenance-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    require_roles(READ_ROLES)
    window = get_or_404(store.maintenance_windows, window_id, "maintenance window")
    return success_object(entity_out(window))


@bp.route("/maintenance-windows/<window_id>/complete", methods=["POST"])
def complete_window(window_id):
    require_roles({"MaintenanceTech"})
    window = get_or_404(store.maintenance_windows, window_id, "maintenance window")
    if window["status"] != "ACTIVE":
        raise errors.invalid_state("maintenance window is not ACTIVE")
    window["status"] = "COMPLETE"
    bump(window)
    unit = store.drive_units.get(window["drive_unit_id"])
    if unit is not None and unit["status"] == "MAINTENANCE":
        unit["status"] = "ACTIVE"
        bump(unit)
    return success_object(entity_out(window))


@bp.route("/maintenance-windows/<window_id>/cancel", methods=["POST"])
def cancel_window(window_id):
    require_roles({"MaintenanceTech"})
    window = get_or_404(store.maintenance_windows, window_id, "maintenance window")
    if window["status"] != "SCHEDULED":
        raise errors.invalid_state("maintenance window is not SCHEDULED")
    if store.clock >= window["_starts_dt"]:
        raise errors.temporal_conflict("window already started")
    window["status"] = "CANCELLED"
    bump(window)
    return success_object(entity_out(window))
