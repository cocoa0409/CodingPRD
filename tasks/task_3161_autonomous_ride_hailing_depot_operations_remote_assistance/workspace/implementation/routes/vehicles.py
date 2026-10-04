"""Vehicle endpoints and the depot service-cycle machinery.

A vehicle is a parallel-state entity: `status` is its lifecycle dimension and
`service_status` is the derived readiness verdict that is recomputed on every
relevant mutation (PRD 2.5).  A DepotCycle walks STAGED -> IN_PROGRESS ->
COMPLETED/ABORTED and applies exactly one service effect on completion.
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    DEPOT_TECHNICIAN,
    FLEET_OPERATIONS,
    REMOTE_ASSISTANCE_OPERATOR,
    SAFETY_REVIEWER,
    TERRITORY_PLANNER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_bool,
    optional_int,
    require_enum,
    require_int,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("vehicles", __name__)

_VEHICLE_READERS = (
    FLEET_OPERATIONS,
    DEPOT_TECHNICIAN,
    REMOTE_ASSISTANCE_OPERATOR,
    TERRITORY_PLANNER,
    SAFETY_REVIEWER,
)

DEFAULT_CLEANLINESS_SCORE = 100
DEFAULT_CALIB_VALID = False


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── Vehicle ──────────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/vehicles")
def create_vehicle(territory_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    vin = require_str(body, "vin")
    battery_pct = require_int(body, "battery_pct", minimum=0)
    cleanliness_score = optional_int(body, "cleanliness_score", DEFAULT_CLEANLINESS_SCORE, minimum=0)
    calib_valid = optional_bool(body, "calib_valid", DEFAULT_CALIB_VALID)
    software_version = require_str(body, "software_version")
    target_software_version = require_str(body, "target_software_version")

    for existing in store.vehicles.values():
        if existing["territory_id"] == territory_id and existing["vin"] == vin:
            raise fail("ERR_DUPLICATE_RESOURCE")

    vehicle = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "vin": vin,
        # status, verdict, credit and version are minted by the server.
        "status": "DRAFT",
        "service_status": "UNAVAILABLE",
        "battery_pct": battery_pct,
        "cleanliness_score": cleanliness_score,
        "calib_valid": calib_valid,
        "software_version": software_version,
        "target_software_version": target_software_version,
        "credit_cents": 0,
        "is_roadside_blocked": False,
        "current_depot_id": None,
        "delay_ops_runs": 0,
        "version": 1,
    }
    store.stamp_create(vehicle)
    store.vehicles[vehicle["id"]] = vehicle
    return success_object(vehicle, 201)


@bp.get("/fleet/territories/<territory_id>/vehicles")
def list_territory_vehicles(territory_id):
    _resolve(_VEHICLE_READERS)
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.vehicles.values() if row["territory_id"] == territory_id]
    rows = _filter_vehicles(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/vehicles")
def list_vehicles():
    _resolve((ANY,))
    rows = list(store.vehicles.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter_vehicles(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter_vehicles(rows, params):
    for param, field in (
        ("status", "status"),
        ("service_status", "service_status"),
        ("current_depot_id", "current_depot_id"),
    ):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    _resolve(_VEHICLE_READERS)
    return success_object(get_or_404(store.vehicles, vehicle_id))


@bp.post("/fleet/vehicles/<vehicle_id>/stage")
def stage_vehicle(vehicle_id):
    _resolve((FLEET_OPERATIONS, DEPOT_TECHNICIAN))
    vehicle = get_or_404(store.vehicles, vehicle_id)
    body = body_object(request.get_json(silent=True))
    depot_id = require_str(body, "depot_id")
    depot = get_or_404(store.depots, depot_id)
    if vehicle["status"] not in ("DRAFT", "IN_SERVICE"):
        raise fail("ERR_INVALID_STATE")
    if depot["territory_id"] != vehicle["territory_id"]:
        raise fail("ERR_CROSS_TERRITORY")
    vehicle["status"] = "AT_DEPOT"
    vehicle["current_depot_id"] = depot_id
    calc.recompute_service_status(vehicle)
    return success_object(vehicle)


@bp.post("/fleet/vehicles/<vehicle_id>/return-to-service")
def return_vehicle_to_service(vehicle_id):
    _resolve((FLEET_OPERATIONS,))
    vehicle = get_or_404(store.vehicles, vehicle_id)
    if vehicle["status"] != "AT_DEPOT":
        raise fail("ERR_INVALID_STATE")
    if vehicle["is_roadside_blocked"] is True:
        raise fail("ERR_VEHICLE_ROADSIDE_BLOCKED")
    if calc.compute_service_status(vehicle) != "AVAILABLE":
        raise fail("ERR_VEHICLE_NOT_SERVICE_READY")
    vehicle["status"] = "IN_SERVICE"
    vehicle["current_depot_id"] = None
    calc.recompute_service_status(vehicle)
    return success_object(vehicle)


@bp.post("/fleet/vehicles/<vehicle_id>/suspend")
def suspend_vehicle(vehicle_id):
    _resolve((SAFETY_REVIEWER,))
    vehicle = get_or_404(store.vehicles, vehicle_id)
    if vehicle["status"] != "AT_DEPOT":
        raise fail("ERR_INVALID_STATE")
    for cycle in store.cycles.values():
        if cycle["vehicle_id"] == vehicle_id and cycle["status"] == "IN_PROGRESS":
            raise fail("ERR_VEHICLE_HAS_ACTIVE_CYCLE")
    vehicle["status"] = "SUSPENDED"
    calc.recompute_service_status(vehicle)
    return success_object(vehicle)


@bp.post("/fleet/vehicles/<vehicle_id>/clear-suspension")
def clear_vehicle_suspension(vehicle_id):
    _resolve((SAFETY_REVIEWER,))
    vehicle = get_or_404(store.vehicles, vehicle_id)
    if vehicle["status"] != "SUSPENDED":
        raise fail("ERR_INVALID_STATE")
    vehicle["status"] = "DRAFT"
    calc.recompute_service_status(vehicle)
    return success_object(vehicle)


# ─── DepotCycle ───────────────────────────────────────────────────────────


@bp.post("/fleet/depots/<depot_id>/cycles")
def create_cycle(depot_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    body = body_object(request.get_json(silent=True))
    vehicle_id = require_str(body, "vehicle_id")
    service_kind = require_enum(body, "service_kind", calc.SERVICE_KINDS)
    vehicle = store.vehicles.get(vehicle_id)
    if vehicle is None:
        raise fail("ERR_NOT_FOUND")
    # A cycle belongs to the depot's own territory.
    if vehicle["territory_id"] != depot["territory_id"]:
        raise fail("ERR_CROSS_TERRITORY")

    cycle = {
        "id": store.new_id(),
        "depot_id": depot_id,
        "vehicle_id": vehicle_id,
        "service_kind": service_kind,
        "status": "STAGED",
        "is_scheduled": False,
        "last_ops_run_index": depot["ops_run_index"],
        "version": 1,
    }
    store.stamp_create(cycle)
    store.cycles[cycle["id"]] = cycle
    return success_object(cycle, 201)


@bp.get("/fleet/depots/<depot_id>/cycles")
def list_depot_cycles(depot_id):
    _resolve((FLEET_OPERATIONS, DEPOT_TECHNICIAN))
    get_or_404(store.depots, depot_id)
    rows = [row for row in store.cycles.values() if row["depot_id"] == depot_id]
    rows = _filter_cycles(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/cycles")
def list_cycles():
    _resolve((ANY,))
    rows = list(store.cycles.values())
    depot_id = request.args.get("depot_id")
    if depot_id:
        rows = [row for row in rows if row["depot_id"] == depot_id]
    rows = _filter_cycles(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter_cycles(rows, params):
    for param, field in (("vehicle_id", "vehicle_id"), ("status", "status")):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/cycles/<cycle_id>")
def get_cycle(cycle_id):
    _resolve((FLEET_OPERATIONS, DEPOT_TECHNICIAN))
    return success_object(get_or_404(store.cycles, cycle_id))


@bp.post("/fleet/depots/<depot_id>/cycles/<cycle_id>/schedule")
def schedule_cycle(depot_id, cycle_id):
    _resolve((DEPOT_TECHNICIAN,))
    get_or_404(store.depots, depot_id)
    cycle = get_or_404(store.cycles, cycle_id)
    body = body_object(request.get_json(silent=True))
    bay_slot_id = require_str(body, "bay_slot_id")
    slot = get_or_404(store.bay_slots, bay_slot_id)
    cycle["is_scheduled"] = True
    slot["cycle_id"] = cycle["id"]
    slot["vehicle_id"] = cycle["vehicle_id"]
    store.touch(cycle)
    return success_object(cycle)


@bp.post("/fleet/depots/<depot_id>/cycles/<cycle_id>/start")
def start_cycle(depot_id, cycle_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    cycle = get_or_404(store.cycles, cycle_id)

    if cycle["is_scheduled"] is not True:
        raise fail("ERR_INVALID_STATE")
    for other in store.cycles.values():
        if other["id"] == cycle["id"]:
            continue
        if other["vehicle_id"] == cycle["vehicle_id"] and other["status"] == "IN_PROGRESS":
            raise fail("ERR_VEHICLE_IN_CYCLE")
    if depot["posture"] == "LOCKDOWN":
        raise fail("ERR_POSTURE_LOCKDOWN")

    cycle["status"] = "IN_PROGRESS"
    store.touch(cycle)
    slot = _scheduled_slot(cycle["id"])
    if slot is not None:
        slot["status"] = "ACTIVE"
        store.touch(slot)
    calc.recompute_depot(depot)
    return success_object(cycle)


@bp.post("/fleet/depots/<depot_id>/cycles/<cycle_id>/complete")
def complete_cycle(depot_id, cycle_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    cycle = get_or_404(store.cycles, cycle_id)
    body = body_object(request.get_json(silent=True))

    if cycle["status"] != "IN_PROGRESS":
        raise fail("ERR_INVALID_STATE")

    service_kind = cycle["service_kind"]
    cleanliness_score = None
    signed_off = None
    if service_kind == calc.KIND_CLEAN:
        if body.get("cleanliness_score") is None:
            raise fail("ERR_INVALID_REQUEST")
        cleanliness_score = require_int(body, "cleanliness_score", minimum=0)
    if service_kind == calc.KIND_CALIBRATION:
        if body.get("signed_off") is not True:
            raise fail("ERR_CALIBRATION_SIGNOFF_REQUIRED")
        signed_off = True

    vehicle = store.vehicles.get(cycle["vehicle_id"])
    if vehicle is not None:
        if service_kind == calc.KIND_CHARGE:
            vehicle["battery_pct"] = 100
        elif service_kind == calc.KIND_CLEAN:
            vehicle["cleanliness_score"] = cleanliness_score
        elif service_kind == calc.KIND_CALIBRATION:
            vehicle["calib_valid"] = signed_off
        elif service_kind == calc.KIND_SOFTWARE:
            vehicle["software_version"] = vehicle["target_software_version"]
        store.touch(vehicle)
        calc.recompute_service_status(vehicle, bump=False)

    cycle["status"] = "COMPLETED"
    store.touch(cycle)
    slot = _scheduled_slot(cycle["id"])
    if slot is not None:
        slot["status"] = "COMPLETED"
        store.touch(slot)
    calc.recompute_depot(depot)
    return success_object(cycle)


@bp.post("/fleet/depots/<depot_id>/cycles/<cycle_id>/abort")
def abort_cycle(depot_id, cycle_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    cycle = get_or_404(store.cycles, cycle_id)
    if cycle["status"] != "IN_PROGRESS":
        raise fail("ERR_INVALID_STATE")

    cycle["status"] = "ABORTED"
    store.touch(cycle)
    slot = _scheduled_slot(cycle["id"])
    if slot is not None:
        slot["status"] = "RELEASED"
        store.touch(slot)
    vehicle = store.vehicles.get(cycle["vehicle_id"])
    if vehicle is not None:
        calc.recompute_service_status(vehicle)
    calc.recompute_depot(depot)
    return success_object(cycle)


def _scheduled_slot(cycle_id):
    for slot in store.bay_slots.values():
        if slot["cycle_id"] == cycle_id and slot["status"] in ("RESERVED", "ACTIVE"):
            return slot
    for slot in store.bay_slots.values():
        if slot["cycle_id"] == cycle_id:
            return slot
    return None