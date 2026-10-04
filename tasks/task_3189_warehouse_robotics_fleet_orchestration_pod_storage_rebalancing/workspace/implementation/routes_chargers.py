"""Chargers and charging sessions blueprint."""

from flask import Blueprint, request

import errors
from calculations import charge_cycle_credit
from cascades import entity_out, list_out, maybe_auto_preventive_window
from db import store
from middleware import require_roles
from models import base_entity, bump, fmt_iso, get_or_404, now_iso, req_int, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("chargers", __name__)

READ_ROLES = {"FleetAdmin", "FlowController", "MaintenanceTech"}


@bp.route("/chargers", methods=["POST"])
def create_charger():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    zone_id = require_field(body, "zone_id")
    if not isinstance(zone_id, str):
        raise errors.validation("zone_id must be a string")
    get_or_404(store.zones, zone_id, "zone")
    slot_count = req_int(body, "slot_count", minimum=1)
    charger = base_entity()
    charger.update({"zone_id": zone_id, "slot_count": slot_count, "slots_in_use": 0})
    store.chargers[charger["id"]] = charger
    return success_object(entity_out(charger), status=201)


@bp.route("/chargers/<charger_id>", methods=["GET"])
def get_charger(charger_id):
    require_roles(READ_ROLES)
    charger = get_or_404(store.chargers, charger_id, "charger")
    return success_object(entity_out(charger))


@bp.route("/chargers/<charger_id>/charging-sessions", methods=["GET"])
def charger_sessions(charger_id):
    require_roles(READ_ROLES)
    get_or_404(store.chargers, charger_id, "charger")
    limit, offset = parse_pagination()
    items = sorted(
        (s for s in store.charging_sessions.values() if s["charger_id"] == charger_id),
        key=lambda s: s["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/charging-sessions", methods=["POST"])
def open_session():
    require_roles({"FlowController"})
    body = request.get_json(silent=True) or {}
    charger_id = require_field(body, "charger_id")
    drive_unit_id = require_field(body, "drive_unit_id")
    if not isinstance(charger_id, str) or not isinstance(drive_unit_id, str):
        raise errors.validation("charger_id and drive_unit_id must be strings")
    charger = get_or_404(store.chargers, charger_id, "charger")
    unit = get_or_404(store.drive_units, drive_unit_id, "drive unit")
    if unit["status"] != "ACTIVE":
        raise errors.invalid_state("drive unit is not ACTIVE")
    zone = store.zones.get(charger["zone_id"])
    if zone is not None and zone.get("posture") == "FROZEN":
        raise errors.safety_interlock("charger zone is FROZEN")
    if charger["slots_in_use"] >= charger["slot_count"]:
        raise errors.capacity_exceeded("charger slots full")
    session = base_entity()
    session.update(
        {
            "charger_id": charger_id,
            "drive_unit_id": drive_unit_id,
            "started_at": now_iso(),
            "ended_at": None,
            "status": "OPEN",
            "charge_credit_pct": None,
            "_started_dt": store.clock,
        }
    )
    store.charging_sessions[session["id"]] = session
    unit["status"] = "CHARGING"
    bump(unit)
    charger["slots_in_use"] += 1
    bump(charger)
    return success_object(entity_out(session), status=201)


@bp.route("/charging-sessions", methods=["GET"])
def list_sessions():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    charger_f = request.args.get("charger_id")
    unit_f = request.args.get("drive_unit_id")
    status_f = request.args.get("status")
    items = list(store.charging_sessions.values())
    if charger_f is not None:
        items = [s for s in items if s["charger_id"] == charger_f]
    if unit_f is not None:
        items = [s for s in items if s["drive_unit_id"] == unit_f]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/charging-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    require_roles(READ_ROLES)
    session = get_or_404(store.charging_sessions, session_id, "charging session")
    return success_object(entity_out(session))


@bp.route("/charging-sessions/<session_id>/close", methods=["POST"])
def close_session(session_id):
    require_roles({"FlowController"})
    session = get_or_404(store.charging_sessions, session_id, "charging session")
    if session["status"] != "OPEN":
        raise errors.invalid_state("charging session is not OPEN")
    session["status"] = "CLOSED"
    session["ended_at"] = now_iso()
    credit = charge_cycle_credit(session["_started_dt"], store.clock)
    session["charge_credit_pct"] = credit
    bump(session)
    charger = store.chargers.get(session["charger_id"])
    if charger is not None:
        charger["slots_in_use"] = max(0, charger["slots_in_use"] - 1)
        bump(charger)
    unit = store.drive_units.get(session["drive_unit_id"])
    if unit is not None:
        unit["battery_pct"] = min(100, unit["battery_pct"] + credit)
        unit["charge_cycle_count"] += 1
        unit["status"] = "ACTIVE"
        bump(unit)
        maybe_auto_preventive_window(unit)
    return success_object(entity_out(session))
