"""Floor exceptions blueprint."""

from flask import Blueprint, request

import errors
from cascades import (
    entity_out,
    fail_pick_task_for_stranded,
    list_out,
    park_zone_units,
    unpark_zone_units,
)
from db import store
from middleware import require_roles
from models import base_entity, bump, get_or_404, req_enum, require_field
from response import parse_pagination, success_list, success_object

bp = Blueprint("floor_exceptions", __name__)

READ_ROLES = {"FleetAdmin", "FloorSupervisor", "SafetyOfficer"}
REPORT_ROLES = {"FloorSupervisor", "FlowController"}


@bp.route("/floor-exceptions", methods=["POST"])
def report_exception():
    require_roles(REPORT_ROLES)
    body = request.get_json(silent=True) or {}
    kind = req_enum(body, "kind", {"DROPPED_ITEM", "BLOCKED_PATH", "STRANDED_ROBOT"})
    zone_id = require_field(body, "zone_id")
    if not isinstance(zone_id, str):
        raise errors.validation("zone_id must be a string")
    get_or_404(store.zones, zone_id, "zone")
    pod_id = body.get("pod_id")
    drive_unit_id = body.get("drive_unit_id")
    # Existence checks for provided FKs (priority 4) before referential shape.
    if pod_id is not None:
        if not isinstance(pod_id, str):
            raise errors.validation("pod_id must be a string")
        get_or_404(store.pods, pod_id, "pod")
    if drive_unit_id is not None:
        if not isinstance(drive_unit_id, str):
            raise errors.validation("drive_unit_id must be a string")
        get_or_404(store.drive_units, drive_unit_id, "drive unit")
    # Referential shape: drive_unit_id required iff kind == STRANDED_ROBOT;
    # pod_id only for DROPPED_ITEM.
    if kind == "STRANDED_ROBOT":
        if drive_unit_id is None:
            raise errors.referential_mismatch(
                "drive_unit_id required for STRANDED_ROBOT"
            )
        if pod_id is not None:
            raise errors.referential_mismatch(
                "pod_id not allowed for STRANDED_ROBOT"
            )
    elif kind == "DROPPED_ITEM":
        if drive_unit_id is not None:
            raise errors.referential_mismatch(
                "drive_unit_id only allowed for STRANDED_ROBOT"
            )
    else:  # BLOCKED_PATH
        if drive_unit_id is not None or pod_id is not None:
            raise errors.referential_mismatch(
                "pod_id/drive_unit_id not allowed for BLOCKED_PATH"
            )
    exception = base_entity()
    exception.update(
        {
            "kind": kind,
            "zone_id": zone_id,
            "pod_id": pod_id,
            "drive_unit_id": drive_unit_id,
            "status": "OPEN",
        }
    )
    store.floor_exceptions[exception["id"]] = exception
    # STRANDED_ROBOT cascade: unit EN_ROUTE -> STRANDED; in-flight task FAILED.
    if kind == "STRANDED_ROBOT":
        unit = store.drive_units.get(drive_unit_id)
        if unit is not None and unit["status"] == "EN_ROUTE":
            unit["status"] = "STRANDED"
            bump(unit)
            for task in store.pick_tasks.values():
                if (
                    task.get("drive_unit_id") == unit["id"]
                    and task["status"] == "DISPATCHED"
                ):
                    fail_pick_task_for_stranded(task)
    return success_object(entity_out(exception), status=201)


@bp.route("/floor-exceptions", methods=["GET"])
def list_exceptions():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.floor_exceptions.values())
    for key in ("zone_id", "status", "pod_id", "drive_unit_id"):
        f = request.args.get(key)
        if f is not None:
            items = [e for e in items if e.get(key) == f]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/floor-exceptions/<exception_id>", methods=["GET"])
def get_exception(exception_id):
    require_roles(READ_ROLES)
    exception = get_or_404(store.floor_exceptions, exception_id, "floor exception")
    return success_object(entity_out(exception))


@bp.route("/floor-exceptions/<exception_id>/triage", methods=["POST"])
def triage_exception(exception_id):
    user_id, role = require_roles({"FloorSupervisor"})
    exception = get_or_404(store.floor_exceptions, exception_id, "floor exception")
    body = request.get_json(silent=True) or {}
    branch = req_enum(body, "branch", {"ROBOT", "HUMAN"})
    if exception["status"] != "OPEN":
        raise errors.invalid_state("floor exception is not OPEN")
    if branch == "ROBOT" and exception["kind"] not in {"DROPPED_ITEM", "BLOCKED_PATH"}:
        raise errors.invalid_state("robotic branch not available for this kind")
    exception["status"] = "TRIAGED_ROBOT" if branch == "ROBOT" else "TRIAGED_HUMAN"
    exception["_triaged_by"] = user_id
    bump(exception)
    zone = store.zones.get(exception["zone_id"])
    if zone is not None and zone.get("posture") == "OPEN":
        zone["posture"] = "RESTRICTED"
        bump(zone)
        park_zone_units(zone["id"])
    return success_object(entity_out(exception))


@bp.route("/floor-exceptions/<exception_id>/resolve", methods=["POST"])
def resolve_exception(exception_id):
    require_roles({"FloorSupervisor"})
    exception = get_or_404(store.floor_exceptions, exception_id, "floor exception")
    body = request.get_json(silent=True) or {}
    corrective_outcome = req_enum(body, "corrective_outcome", {"RESTORE", "MAINTENANCE"})
    if exception["status"] not in {"TRIAGED_ROBOT", "TRIAGED_HUMAN"}:
        raise errors.invalid_state("floor exception is not triaged")
    if corrective_outcome == "MAINTENANCE" and exception["kind"] != "STRANDED_ROBOT":
        raise errors.validation("MAINTENANCE outcome valid only for STRANDED_ROBOT")
    if exception["status"] == "TRIAGED_ROBOT":
        if corrective_outcome != "RESTORE":
            raise errors.validation("TRIAGED_ROBOT resolution requires RESTORE")
        # No ACTIVE permit may cover the zone.
        for permit in store.human_entry_permits.values():
            if permit["zone_id"] == exception["zone_id"] and permit["status"] == "ACTIVE":
                raise errors.safety_interlock("active human-entry permit covers zone")
    else:  # TRIAGED_HUMAN
        permits = [
            p
            for p in store.human_entry_permits.values()
            if p.get("exception_id") == exception["id"]
        ]
        for permit in permits:
            if permit["status"] != "RELEASED":
                raise errors.safety_interlock(
                    "all permits for the exception must be RELEASED"
                )
    exception["status"] = "RESOLVED"
    bump(exception)
    zone = store.zones.get(exception["zone_id"])
    if zone is not None:
        zone["posture"] = "OPEN"
        bump(zone)
        unpark_zone_units(zone["id"])
    if exception["kind"] == "STRANDED_ROBOT" and exception.get("drive_unit_id"):
        unit = store.drive_units.get(exception["drive_unit_id"])
        if unit is not None and unit["status"] == "STRANDED":
            if corrective_outcome == "MAINTENANCE":
                unit["status"] = "MAINTENANCE"
            else:
                unit["status"] = "ACTIVE"
            bump(unit)
    if exception.get("pod_id"):
        pod = store.pods.get(exception["pod_id"])
        if pod is not None and pod["status"] == "QUARANTINED":
            pod["status"] = "IN_STORAGE"
            bump(pod)
    return success_object(entity_out(exception))
