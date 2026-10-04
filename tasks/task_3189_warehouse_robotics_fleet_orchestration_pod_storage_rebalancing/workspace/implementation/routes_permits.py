"""Human entry permits blueprint."""

from flask import Blueprint, request

import errors
from cascades import entity_out, freeze_zone_units, list_out
from db import store
from middleware import require_roles
from models import (
    base_entity,
    bump,
    fmt_iso,
    get_or_404,
    parse_iso,
    require_field,
)
from response import parse_pagination, success_list, success_object

bp = Blueprint("human_entry_permits", __name__)

READ_ROLES = {"FleetAdmin", "FloorSupervisor", "SafetyOfficer"}


def _closed_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.route("/human-entry-permits", methods=["POST"])
def request_permit():
    require_roles({"FloorSupervisor"})
    body = request.get_json(silent=True) or {}
    zone_id = require_field(body, "zone_id")
    exception_id = require_field(body, "exception_id")
    if not isinstance(zone_id, str) or not isinstance(exception_id, str):
        raise errors.validation("zone_id and exception_id must be strings")
    get_or_404(store.zones, zone_id, "zone")
    exception = get_or_404(store.floor_exceptions, exception_id, "floor exception")
    starts_raw = require_field(body, "starts_at")
    ends_raw = require_field(body, "ends_at")
    starts_dt = parse_iso(starts_raw, "starts_at")
    ends_dt = parse_iso(ends_raw, "ends_at")
    if exception["status"] != "TRIAGED_HUMAN":
        raise errors.referential_mismatch("exception is not TRIAGED_HUMAN")
    # Closed interval: ends_at >= starts_at.
    if ends_dt < starts_dt:
        raise errors.temporal_conflict("ends_at must be >= starts_at")
    permit = base_entity()
    permit.update(
        {
            "zone_id": zone_id,
            "exception_id": exception_id,
            "starts_at": fmt_iso(starts_dt),
            "ends_at": fmt_iso(ends_dt),
            "status": "REQUESTED",
            "_starts_dt": starts_dt,
            "_ends_dt": ends_dt,
        }
    )
    store.human_entry_permits[permit["id"]] = permit
    return success_object(entity_out(permit), status=201)


@bp.route("/human-entry-permits", methods=["GET"])
def list_permits():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.human_entry_permits.values())
    for key in ("zone_id", "exception_id", "status"):
        f = request.args.get(key)
        if f is not None:
            items = [p for p in items if p.get(key) == f]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/human-entry-permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    require_roles(READ_ROLES)
    permit = get_or_404(store.human_entry_permits, permit_id, "human entry permit")
    return success_object(entity_out(permit))


@bp.route("/human-entry-permits/<permit_id>/grant", methods=["POST"])
def grant_permit(permit_id):
    user_id, role = require_roles({"SafetyOfficer"})
    permit = get_or_404(store.human_entry_permits, permit_id, "human entry permit")
    if permit["status"] != "REQUESTED":
        raise errors.invalid_state("permit is not REQUESTED")
    exception = store.floor_exceptions.get(permit["exception_id"])
    if exception is None:
        raise errors.not_found("governing exception missing")
    if exception["status"] != "TRIAGED_HUMAN":
        raise errors.invalid_state("governing exception is not TRIAGED_HUMAN")
    # Segregation of duties: SafetyOfficer must differ from triaging supervisor.
    if exception.get("_triaged_by") is not None and exception["_triaged_by"] == user_id:
        raise errors.safety_interlock(
            "segregation of duties: officer must differ from triaging supervisor"
        )
    zone = store.zones.get(permit["zone_id"])
    if zone is None:
        raise errors.not_found("zone missing")
    overlapping_active = 0
    for other in store.human_entry_permits.values():
        if other["id"] == permit["id"]:
            continue
        if other["zone_id"] != permit["zone_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if _closed_overlap(
            permit["_starts_dt"], permit["_ends_dt"], other["_starts_dt"], other["_ends_dt"]
        ):
            overlapping_active += 1
    if overlapping_active >= zone["max_human_occupancy"]:
        raise errors.capacity_exceeded("zone at max human occupancy")
    permit["status"] = "ACTIVE"
    bump(permit)
    zone["posture"] = "FROZEN"
    bump(zone)
    freeze_zone_units(zone["id"])
    return success_object(entity_out(permit))


@bp.route("/human-entry-permits/<permit_id>/release", methods=["POST"])
def release_permit(permit_id):
    require_roles({"SafetyOfficer"})
    permit = get_or_404(store.human_entry_permits, permit_id, "human entry permit")
    if permit["status"] != "ACTIVE":
        raise errors.invalid_state("permit is not ACTIVE")
    if store.clock < permit["_ends_dt"]:
        raise errors.invalid_state("current clock before permit ends_at")
    permit["status"] = "RELEASED"
    bump(permit)
    zone = store.zones.get(permit["zone_id"])
    if zone is not None:
        other_active = any(
            p["zone_id"] == permit["zone_id"] and p["status"] == "ACTIVE"
            for p in store.human_entry_permits.values()
            if p["id"] != permit["id"]
        )
        if not other_active and zone.get("posture") == "FROZEN":
            zone["posture"] = "RESTRICTED"
            bump(zone)
    return success_object(entity_out(permit))
