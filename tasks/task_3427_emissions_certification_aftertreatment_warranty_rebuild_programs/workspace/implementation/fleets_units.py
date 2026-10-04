"""Fleets, engine units, coverage read, maintenance records (PRD §3.4)."""
from flask import Blueprint, request

import calculations
import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_bool, f_enum, f_dt, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, new_append, touch, ser,
)

bp = Blueprint("fleets_units", __name__)

MAINTENANCE_TYPES = ("OIL_CHANGE", "DPF_CLEAN", "DEF_SERVICE", "VALVE_ADJUST", "SENSOR_REPLACE")


# ---------------------------------------------------------------------------
# Fleets
# ---------------------------------------------------------------------------

@bp.post("/emissions/fleets")
def create_fleet():
    auth(("PlatformAdmin",))
    b = body()
    name = f_str(b, "name")
    fleet_code = f_str(b, "fleet_code")
    contact = f_str(b, "notification_contact")
    ent = new_entity()
    ent.update({
        "name": name,
        "fleet_code": fleet_code,
        "notification_contact": contact,
        "status": "ACTIVE",
        "neglect_denial_count": 0,
    })
    store.fleets[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/fleets/<fid>")
def get_fleet(fid):
    auth(ANY)
    ent = get_or_404(store.fleets, fid, "Fleet")
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/fleets/<fid>/reinstate")
def reinstate_fleet(fid):
    auth(("PlatformAdmin",))
    fleet = get_or_404(store.fleets, fid, "Fleet")
    if fleet["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "reinstate requires SUSPENDED")
    fleet["status"] = "ACTIVE"
    fleet["neglect_denial_count"] = 0
    touch(fleet)
    return envelope_ok(ser(fleet), 200)


@bp.get("/emissions/fleets/<fid>/engine-units")
def fleet_units(fid):
    auth(ANY)
    limit, offset = page_args()
    get_or_404(store.fleets, fid, "Fleet")
    items = [u for u in store.units.values() if u["fleet_id"] == fid]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


# ---------------------------------------------------------------------------
# Engine units
# ---------------------------------------------------------------------------

@bp.post("/emissions/engine-units")
def create_unit():
    auth(("PlatformAdmin",))
    b = body()
    family_id = f_str(b, "engine_family_id")
    fleet_id = f_str(b, "fleet_id")
    serial = f_str(b, "serial_number")
    in_service = f_dt(b, "in_service_date")
    fam = get_or_404(store.families, family_id, "EngineFamily")
    get_or_404(store.fleets, fleet_id, "Fleet")
    # state gate (priority 7)
    if fam["certification_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_FAMILY_NOT_IN_PRODUCTION", 409,
                       "Unit registration requires the family IN_PRODUCTION")
    # uniqueness (priority 11): serial unique within the family
    for u in store.units.values():
        if u["engine_family_id"] == family_id and u["serial_number"] == serial:
            raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER", 409,
                           "serial_number already exists within the family")
    # temporal (priority 12): strictly-after-the-clock is rejected; equality accepted
    if in_service > clock.now_dt():
        raise ApiError("ERR_IN_SERVICE_DATE_IN_FUTURE", 422,
                       "in_service_date lies after the logical clock")
    ent = new_entity()
    ent.update({
        "engine_family_id": family_id,
        "fleet_id": fleet_id,
        "serial_number": serial,
        "model_year": fam["model_year"],  # copied from family; client input ignored
        "in_service_date": in_service,
        "accumulated_miles": 0,
        "accumulated_hours": 0,
        "lifecycle": "IN_SERVICE",
        "campaign_compliance": "CLEAR",
        "predictive_service_due": False,
        "last_snapshot_at": None,
    })
    store.units[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/engine-units")
def list_units():
    auth(ANY)
    limit, offset = page_args()
    items = list(store.units.values())
    for param, key in (("engine_family_id", "engine_family_id"),
                       ("fleet_id", "fleet_id"),
                       ("lifecycle", "lifecycle"),
                       ("campaign_compliance", "campaign_compliance")):
        v = request.args.get(param)
        if v is not None:
            items = [u for u in items if u[key] == v]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/engine-units/<uid>")
def get_unit(uid):
    auth(ANY)
    ent = get_or_404(store.units, uid, "EngineUnit")
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/engine-units/<uid>/decommission")
def decommission_unit(uid):
    auth(("PlatformAdmin",))
    unit = get_or_404(store.units, uid, "EngineUnit")
    if unit["lifecycle"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "decommission requires IN_SERVICE")
    if any(w["engine_unit_id"] == uid and w["status"] in ("SCHEDULED", "IN_BAY")
           for w in store.work_orders.values()):
        raise ApiError("ERR_WORK_ORDERS_OUTSTANDING", 409,
                       "Work orders in SCHEDULED or IN_BAY block decommission")
    if any(r["engine_unit_id"] == uid
           and r["status"] in ("QUOTED", "AWAITING_CORE", "CORE_RECEIVED")
           for r in store.reman_orders.values()):
        raise ApiError("ERR_REMAN_ORDER_OPEN", 409,
                       "An open reman order blocks decommission")
    unit["lifecycle"] = "DECOMMISSIONED"
    touch(unit)
    return envelope_ok(ser(unit), 200)


@bp.get("/emissions/engine-units/<uid>/coverage")
def unit_coverage(uid):
    auth(ANY)
    unit = get_or_404(store.units, uid, "EngineUnit")
    fam = store.families.get(unit["engine_family_id"])
    std = store.standards.get(fam["regulation_standard_id"]) if fam else None
    cov = calculations.coverage_windows(unit, std, None, clock.now_dt())
    return envelope_ok({
        "base_covered": cov["base_covered"],
        "base_coverage_end": clock.iso(cov["base_coverage_end"]),
        "extended_covered": cov["extended_covered"],
        "extended_coverage_end": clock.iso(cov["extended_coverage_end"]),
        "extended_applies_to": ",".join(calculations.EMISSIONS_COMPONENT_CLASSES),
    }, 200)


# ---------------------------------------------------------------------------
# Maintenance records (append-only)
# ---------------------------------------------------------------------------

@bp.post("/emissions/engine-units/<uid>/maintenance-records")
def create_maintenance_record(uid):
    user_id, role = auth(("FleetManager", "PlatformAdmin"))
    b = body()
    performed_at = f_dt(b, "performed_at")
    mtype = f_enum(b, "maintenance_type", MAINTENANCE_TYPES)
    odometer = f_int(b, "odometer_at_service")
    def_ok = f_bool(b, "def_quality_ok", required=False, default=True)
    unit = get_or_404(store.units, uid, "EngineUnit")
    # ownership (priority 5): FleetManager acts only on own fleet's units
    if role == "FleetManager" and unit["fleet_id"] != user_id:
        raise ApiError("ERR_FLEET_MISMATCH", 403,
                       "FleetManager may act only on units of their own fleet")
    # state gate (priority 7): a suspended fleet's manager may not append records
    if role == "FleetManager":
        fleet = store.fleets.get(unit["fleet_id"])
        if fleet is not None and fleet["status"] == "SUSPENDED":
            raise ApiError("ERR_FLEET_SUSPENDED", 409,
                           "A SUSPENDED fleet may not append maintenance records")
    # temporal (priority 12)
    if odometer > unit["accumulated_miles"]:
        raise ApiError("ERR_ODOMETER_EXCEEDS_UNIT", 422,
                       "odometer_at_service exceeds the unit's accumulated miles")
    rec = new_append()
    rec.update({
        "engine_unit_id": unit["id"],
        "performed_at": performed_at,
        "maintenance_type": mtype,
        "odometer_at_service": odometer,
        "def_quality_ok": def_ok,
    })
    store.maintenance[rec["id"]] = rec
    return envelope_ok(ser(rec), 201)


@bp.get("/emissions/engine-units/<uid>/maintenance-records")
def list_maintenance_records(uid):
    auth(ANY)
    limit, offset = page_args()
    get_or_404(store.units, uid, "EngineUnit")
    items = [r for r in store.maintenance.values() if r["engine_unit_id"] == uid]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)
