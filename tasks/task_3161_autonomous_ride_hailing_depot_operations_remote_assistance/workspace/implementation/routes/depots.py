"""DepotSite endpoints, bay slots and the depot operations checkpoint.

The checkpoint (§3.7) is a single POST that advances the depot's ops epoch and
then sweeps cycle SLA expiries, assistance-session timeouts, staged-vehicle
delay counters and the depot's own posture in the same execution.
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    DEPOT_TECHNICIAN,
    FLEET_OPERATIONS,
    SAFETY_REVIEWER,
    TERRITORY_PLANNER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_enum,
    require_enum,
    require_instant,
    require_int,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("depots", __name__)

_VEHICLE_READERS = (ANY,)


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── DepotSite ────────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/depots")
def create_depot(territory_id):
    _resolve((TERRITORY_PLANNER,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    depot = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "name": require_str(body, "name"),
        "charge_positions": require_int(body, "charge_positions", minimum=0),
        "cleaning_positions": require_int(body, "cleaning_positions", minimum=0),
        "calib_positions": require_int(body, "calib_positions", minimum=0),
        "software_positions": require_int(body, "software_positions", minimum=0),
        "posture": "OPEN",
        "occupancy_pct": 0,
        "ops_run_index": 0,
        "version": 1,
    }
    store.stamp_create(depot)
    store.depots[depot["id"]] = depot
    return success_object(depot, 201)


@bp.get("/fleet/territories/<territory_id>/depots")
def list_territory_depots(territory_id):
    _resolve((ANY,))
    get_or_404(store.territories, territory_id)
    rows = sorted(
        (row for row in store.depots.values() if row["territory_id"] == territory_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/depots")
def list_depots():
    _resolve((ANY,))
    rows = sorted(store.depots.values(), key=lambda row: (row["created_at"], row["id"]))
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/depots/<depot_id>")
def get_depot(depot_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.depots, depot_id))


@bp.get("/fleet/depots/<depot_id>/vehicles")
def list_depot_vehicles(depot_id):
    _resolve((FLEET_OPERATIONS, DEPOT_TECHNICIAN, TERRITORY_PLANNER, SAFETY_REVIEWER))
    get_or_404(store.depots, depot_id)
    rows = sorted(
        (row for row in store.vehicles.values() if row.get("current_depot_id") == depot_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    status = request.args.get("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


# ─── the depot operations checkpoint ──────────────────────────────────────


@bp.post("/fleet/depots/<depot_id>/run-depot-ops")
def run_depot_ops(depot_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    depot["ops_run_index"] = depot["ops_run_index"] + 1
    store.touch(depot)
    epoch = depot["ops_run_index"]

    # 1. Cycle SLA sweep: a cycle stalled for two epochs is abandoned.
    for cycle in _cycles_of(depot_id):
        if cycle["status"] not in ("STAGED", "IN_PROGRESS"):
            continue
        if epoch - cycle["last_ops_run_index"] >= calc.CYCLE_SLA_OPS_RUNS:
            vehicle = store.vehicles.get(cycle["vehicle_id"])
            if vehicle is not None:
                vehicle["status"] = "DRAFT"
                vehicle["current_depot_id"] = None
                store.touch(vehicle)
                calc.recompute_service_status(vehicle, bump=False)
            cycle["status"] = "ABORTED"
            store.touch(cycle)
            for slot in _slots_of_cycle(cycle["id"]):
                if slot["status"] in ("RESERVED", "ACTIVE"):
                    slot["status"] = "RELEASED"
                    store.touch(slot)

    # 2. Assistance timeout sweep: acknowledged across three epochs, re-escalate.
    for session in _sessions_of(depot_id):
        if session["status"] != "ACKNOWLEDGED":
            continue
        if epoch - session["last_ops_run_index"] >= calc.ACK_TIMEOUT_OPS_RUNS:
            session["status"] = "ESCALATED"
            session["escalation_tier"] = session["escalation_tier"] + 1
            session["attempt_count"] = session["attempt_count"] + 1
            session["last_ops_run_index"] = epoch
            store.touch(session)

    # 3. Refresh the staged-vehicle waiting counter.
    for vehicle in store.vehicles.values():
        if vehicle["status"] != "AT_DEPOT":
            continue
        cycle = _open_cycle_for_vehicle(vehicle["id"])
        observed = cycle["last_ops_run_index"] if cycle is not None else 0
        delay = max(0, epoch - observed)
        if vehicle["delay_ops_runs"] != delay:
            vehicle["delay_ops_runs"] = delay
            store.touch(vehicle)

    # 4. Recompute the depot's posture from its live bays.
    calc.recompute_depot(depot, bump=False)
    return success_object(depot)


def _cycles_of(depot_id):
    return sorted(
        (row for row in store.cycles.values() if row["depot_id"] == depot_id),
        key=lambda row: (row["created_at"], row["id"]),
    )


def _slots_of_cycle(cycle_id):
    return [row for row in store.bay_slots.values() if row["cycle_id"] == cycle_id]


def _open_cycle_for_vehicle(vehicle_id):
    for cycle in store.cycles.values():
        if cycle["vehicle_id"] != vehicle_id:
            continue
        if cycle["status"] in ("STAGED", "IN_PROGRESS"):
            return cycle
    return None


def _sessions_of(depot_id):
    """Sessions observed by this depot's operations epoch.

    A session's operations epoch is the depot that services the vehicle it was
    opened for; a vehicle returned to service has no `current_depot_id`, so the
    depot's own territory is the scoping key.
    """
    depot = store.depots.get(depot_id)
    if depot is None:
        return []
    rows = []
    for session in store.assistance_sessions.values():
        vehicle = store.vehicles.get(session["vehicle_id"])
        if vehicle is None:
            continue
        if vehicle["territory_id"] == depot["territory_id"]:
            rows.append(session)
    return rows


# ─── BaySlot ──────────────────────────────────────────────────────────────


@bp.post("/fleet/depots/<depot_id>/bay-slots")
def create_bay_slot(depot_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    body = body_object(request.get_json(silent=True))
    service_type = require_enum(body, "service_type", calc.SERVICE_KINDS)
    bay_index = require_int(body, "bay_index", minimum=0)
    start_utc = require_instant(body, "start_utc")
    duration_seconds = require_int(body, "duration_seconds", minimum=1)
    vehicle_id = require_str(body, "vehicle_id")
    cycle_id = require_str(body, "cycle_id")

    end_utc = _add_seconds(start_utc, duration_seconds)

    # Bay occupancy: the requested half-open window must not intersect an
    # existing RESERVED/ACTIVE slot on the same (depot, service_type, bay_index).
    new_start = calc._instant(start_utc)
    new_end = calc._instant(end_utc)
    for slot in store.bay_slots.values():
        if slot["depot_id"] != depot_id:
            continue
        if slot["service_type"] != service_type or slot["bay_index"] != bay_index:
            continue
        if slot["status"] not in ("RESERVED", "ACTIVE"):
            continue
        if calc._instant(slot["start_utc"]) < new_end and new_start < calc._instant(slot["end_utc"]):
            raise fail("ERR_BAY_SLOT_CONFLICT")

    slot = {
        "id": store.new_id(),
        "depot_id": depot_id,
        "service_type": service_type,
        "bay_index": bay_index,
        "start_utc": _canonical(start_utc),
        "duration_seconds": duration_seconds,
        "end_utc": _canonical(end_utc),
        "vehicle_id": vehicle_id,
        "cycle_id": cycle_id,
        "status": "RESERVED",
        "version": 1,
    }
    store.stamp_create(slot)
    store.bay_slots[slot["id"]] = slot
    calc.recompute_depot(depot)
    return success_object(slot, 201)


@bp.get("/fleet/depots/<depot_id>/bay-slots")
def list_depot_bay_slots(depot_id):
    _resolve((FLEET_OPERATIONS, DEPOT_TECHNICIAN))
    get_or_404(store.depots, depot_id)
    rows = sorted(
        (row for row in store.bay_slots.values() if row["depot_id"] == depot_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    rows = _filter_slots(rows, request.args)
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/bay-slots")
def list_bay_slots():
    _resolve((ANY,))
    rows = sorted(store.bay_slots.values(), key=lambda row: (row["created_at"], row["id"]))
    depot_id = request.args.get("depot_id")
    if depot_id:
        rows = [row for row in rows if row["depot_id"] == depot_id]
    rows = _filter_slots(rows, request.args)
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter_slots(rows, params):
    for param, field in (
        ("service_type", "service_type"),
        ("vehicle_id", "vehicle_id"),
        ("cycle_id", "cycle_id"),
        ("status", "status"),
    ):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/bay-slots/<bay_slot_id>")
def get_bay_slot(bay_slot_id):
    _resolve((FLEET_OPERATIONS, DEPOT_TECHNICIAN))
    return success_object(get_or_404(store.bay_slots, bay_slot_id))


@bp.post("/fleet/depots/<depot_id>/bay-slots/<bay_slot_id>/release")
def release_bay_slot(depot_id, bay_slot_id):
    _resolve((DEPOT_TECHNICIAN,))
    depot = get_or_404(store.depots, depot_id)
    slot = get_or_404(store.bay_slots, bay_slot_id)
    if slot["depot_id"] != depot_id:
        raise fail("ERR_NOT_FOUND")
    if slot["status"] != "RESERVED":
        raise fail("ERR_INVALID_STATE")
    slot["status"] = "RELEASED"
    store.touch(slot)
    calc.recompute_depot(depot)
    return success_object(slot)


# ─── datetime helpers ─────────────────────────────────────────────────────


def _canonical(value):
    from db import format_utc

    return format_utc(calc._instant(value))


def _add_seconds(value, seconds):
    import datetime as dt

    return calc._instant(value) + dt.timedelta(seconds=seconds)