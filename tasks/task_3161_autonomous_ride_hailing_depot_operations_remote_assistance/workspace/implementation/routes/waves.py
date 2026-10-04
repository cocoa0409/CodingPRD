"""Demand curves and staged fleet deployment.

A DemandSignal is keyed by window code and upserted.  A DeploymentWave carries
its own budget and leaves a staged reserve behind on dispatch: the reserve
floor is ceil(6 / planned_vehicle_count), rounded once per wave before the
subtraction (PRD 3.3).
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    FLEET_OPERATIONS,
    TERRITORY_PLANNER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_enum,
    require_enum,
    require_int,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("waves", __name__)


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── DemandSignal ─────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/demand-signals")
def upsert_demand_signal(territory_id):
    _resolve((TERRITORY_PLANNER,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    window_code = require_enum(body, "window_code", calc.WINDOW_CODES)
    projected_rides = require_int(body, "projected_rides", minimum=0)
    manual_only_rides = require_int(body, "manual_only_rides", minimum=0)
    effective = calc.effective_demand(projected_rides, manual_only_rides)

    existing = calc.demand_signal_for(territory_id, window_code)
    if existing is None:
        signal = {
            "id": store.new_id(),
            "territory_id": territory_id,
            "window_code": window_code,
            "projected_rides": projected_rides,
            "manual_only_rides": manual_only_rides,
            "effective_demand": effective,
            "version": 1,
        }
        store.stamp_create(signal)
        store.demand_signals[signal["id"]] = signal
    else:
        # A publish for an existing window replaces the row in place.
        existing["projected_rides"] = projected_rides
        existing["manual_only_rides"] = manual_only_rides
        existing["effective_demand"] = effective
        store.touch(existing)
        signal = existing
    return success_object(signal)


@bp.get("/fleet/territories/<territory_id>/demand-signals")
def list_territory_demand_signals(territory_id):
    _resolve((FLEET_OPERATIONS, TERRITORY_PLANNER))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.demand_signals.values() if row["territory_id"] == territory_id]
    window_code = request.args.get("window_code")
    if window_code:
        rows = [row for row in rows if row["window_code"] == window_code]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/demand-signals")
def list_demand_signals():
    _resolve((ANY,))
    rows = list(store.demand_signals.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    window_code = request.args.get("window_code")
    if window_code:
        rows = [row for row in rows if row["window_code"] == window_code]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/demand-signals/<signal_id>")
def get_demand_signal(signal_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.demand_signals, signal_id))


# ─── DeploymentWave ───────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/deployment-waves")
def create_wave(territory_id):
    _resolve((TERRITORY_PLANNER,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    wave = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "window_code": require_enum(body, "window_code", calc.WINDOW_CODES),
        "planned_vehicle_count": require_int(body, "planned_vehicle_count", minimum=1),
        "deployed_vehicle_count": 0,
        "status": "PLANNED",
        "last_ops_run_index": _territory_epoch(territory_id),
        "version": 1,
    }
    store.stamp_create(wave)
    store.waves[wave["id"]] = wave
    return success_object(wave, 201)


def _territory_epoch(territory_id):
    return sum(depot["ops_run_index"] for depot in store.depots.values() if depot["territory_id"] == territory_id)


@bp.get("/fleet/territories/<territory_id>/deployment-waves")
def list_territory_waves(territory_id):
    _resolve((FLEET_OPERATIONS, TERRITORY_PLANNER))
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.waves.values() if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/deployment-waves")
def list_waves():
    _resolve((ANY,))
    rows = list(store.waves.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter(rows, params):
    for param, field in (("status", "status"), ("window_code", "window_code")):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/deployment-waves/<wave_id>")
def get_wave(wave_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.waves, wave_id))


@bp.post("/fleet/territories/<territory_id>/deployment-waves/<wave_id>/activate")
def activate_wave(territory_id, wave_id):
    _resolve((TERRITORY_PLANNER,))
    territory = get_or_404(store.territories, territory_id)
    wave = get_or_404(store.waves, wave_id)
    if wave["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    body = body_object(request.get_json(silent=True))
    route_class = optional_enum(body, "route_class", ("FREEWAY", "ARTERIAL", "RESIDENTIAL", "ALLEY"))

    # Precedence (PRD 3.7): posture, then the route-class gate, then the
    # exclusion-zone gate, then weather.
    if territory["posture"] != "ACTIVE":
        raise fail("ERR_TERRITORY_NOT_ACTIVE")
    if territory["active_zone_count"] > 0:
        raise fail("ERR_ZONE_BLOCKED_WAVE")
    if route_class is not None:
        if not calc.route_class_allowed(territory_id, route_class):
            raise fail("ERR_ROUTE_NOT_ALLOWED")
        if calc.exclusion_zone_covers(territory_id, route_class):
            raise fail("ERR_EXCLUSION_ZONE_ACTIVE")
    if wave["window_code"] in calc.PEAK_WINDOWS:
        tier = store.weather_tiers.get((territory_id, wave["window_code"]))
        if tier is not None and tier >= 3:
            raise fail("ERR_WEATHER_SUSPENDED")

    wave["status"] = "ACTIVE"
    store.touch(wave)
    return success_object(wave)


@bp.post("/fleet/territories/<territory_id>/deployment-waves/<wave_id>/dispatch")
def dispatch_wave(territory_id, wave_id):
    _resolve((TERRITORY_PLANNER,))
    get_or_404(store.territories, territory_id)
    wave = get_or_404(store.waves, wave_id)
    if wave["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if wave["status"] != "ACTIVE":
        raise fail("ERR_INVALID_STATE")

    candidates = calc.wave_candidates(territory_id)
    cap = calc.wave_allocation_cap(wave["planned_vehicle_count"], len(candidates))
    selected = candidates[:cap]
    for vehicle in selected:
        vehicle["status"] = "IN_SERVICE"
        vehicle["current_depot_id"] = None
        store.touch(vehicle)
        calc.recompute_service_status(vehicle, bump=False)
    wave["deployed_vehicle_count"] = len(selected)
    wave["status"] = "COMPLETED"
    store.touch(wave)
    return success_object(wave)


@bp.post("/fleet/territories/<territory_id>/deployment-waves/<wave_id>/abort")
def abort_wave(territory_id, wave_id):
    _resolve((TERRITORY_PLANNER,))
    get_or_404(store.territories, territory_id)
    wave = get_or_404(store.waves, wave_id)
    if wave["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if wave["status"] not in ("PLANNED", "ACTIVE"):
        raise fail("ERR_INVALID_STATE")
    wave["status"] = "ABORTED"
    store.touch(wave)
    return success_object(wave)