"""Defibrillator Program API — Flask application.

Implements the PRD for placement planning, readiness, response integration,
case review, and replenishment. All state is in-memory; the store starts
empty on every boot. The logical clock defaults to 2026-09-01T00:00:00Z and
is driven through POST /api/_clock/set_current_utc.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

from db import db
from errors import (
    ApiError,
    raise_err,
    not_found,
    invalid_request,
    invalid_state,
    ERR_REPLENISHMENT_INVALID,
    ERR_MEDICAL_DIRECTION_CONFLICT,
    ERR_PRESCRIPTION_REQUIRED,
    ERR_RESPONDER_NOT_CERTIFIED,
    ERR_TEMPORAL_WINDOW_VIOLATION,
    ERR_INCOMPATIBLE_REFERENCE,
    ERR_CAPACITY_EXCEEDED,
    ERR_LOT_UNAVAILABLE,
    ERR_CABINET_NOT_EMPTY,
    ERR_DEVICE_NOT_READY,
    ERR_DEVICE_IN_EVENT,
    ERR_EVENT_ALREADY_ACKED,
    ERR_EVENT_NOT_RESPONDING,
    ERR_INSPECTION_OVERDUE,
    ERR_INSPECTION_CHECKLIST_INCOMPLETE,
    ERR_SESSION_ALREADY_STARTED,
    ERR_SESSION_NOT_ENDED,
    ERR_TRAINING_FULL,
    ERR_INSTRUCTOR_ROLE_INVALID,
    ERR_CASE_REVIEW_INCOMPLETE,
    ERR_SERIAL_NUMBER_CONFLICT,
    ERR_STALE_VERSION,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, error_response
from helpers import (
    add_months,
    body,
    fmt_dt,
    new_entity,
    new_id,
    paginate,
    pagination_params,
    parse_dt,
    req_bool,
    req_enum,
    req_int,
    req_number,
    req_str,
    require_fields,
    touch,
    ts_now,
)
from services import (
    recompute_device_and_campus,
    refresh_campus_posture,
    sweep_device_time_based,
    sweep_all,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_err):
    return error_response(ERR_NOT_FOUND[0], 404, "Resource not found")


@app.errorhandler(405)
def handle_405(_err):
    return error_response(ERR_INVALID_REQUEST[0], 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err: Exception):
    return error_response(ERR_INVALID_REQUEST[0], 400, str(err))


# ---------------------------------------------------------------------------
# Lookups (404 helpers)
# ---------------------------------------------------------------------------

def get_campus_or_404(campus_id):
    c = db.campuses.get(campus_id)
    if c is None:
        not_found("campus")
    return c


def get_zone_or_404(zone_id):
    z = db.zones.get(zone_id)
    if z is None:
        not_found("zone")
    return z


def get_model_or_404(model_id):
    m = db.device_models.get(model_id)
    if m is None:
        not_found("device model")
    return m


def get_cabinet_or_404(cabinet_id):
    c = db.cabinets.get(cabinet_id)
    if c is None:
        not_found("cabinet")
    return c


def get_device_or_404(device_id):
    d = db.devices.get(device_id)
    if d is None:
        not_found("device")
    return d


def get_lot_or_404(lot_id):
    lot = db.consumable_lots.get(lot_id)
    if lot is None:
        not_found("consumable lot")
    return lot


def get_install_or_404(install_id):
    inst = db.installs.get(install_id)
    if inst is None:
        not_found("install")
    return inst


def get_inspection_or_404(inspection_id):
    insp = db.inspections.get(inspection_id)
    if insp is None:
        not_found("inspection")
    return insp


def get_responder_or_404(responder_id):
    r = db.responders.get(responder_id)
    if r is None:
        not_found("responder")
    return r


def get_session_or_404(session_id):
    s = db.training_sessions.get(session_id)
    if s is None:
        not_found("training session")
    return s


def get_event_or_404(event_id):
    e = db.emergency_events.get(event_id)
    if e is None:
        not_found("emergency event")
    return e


def get_review_or_404(review_id):
    r = db.case_reviews.get(review_id)
    if r is None:
        not_found("case review")
    return r


def get_order_or_404(order_id):
    o = db.replenishment_orders.get(order_id)
    if o is None:
        not_found("replenishment order")
    return o


def check_occ(device, data):
    """§2.7 optimistic concurrency on the two OCC-guarded device writes."""
    expected = data.get("expected_device_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid_request("expected_device_version is required and must be an integer")
    if expected != device["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_device_version does not match the device's current version")


def device_fresh(device_id):
    """Fetch device and apply time-driven sweep before returning it."""
    device = get_device_or_404(device_id)
    sweep_device_time_based(device, db.now())
    return device


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.post("/api/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    require_fields(data, ["current_utc"])
    dt = parse_dt(data["current_utc"], "current_utc")
    db.set_clock(dt)
    return success({"current_utc": fmt_dt(dt)})


# ---------------------------------------------------------------------------
# Campuses
# ---------------------------------------------------------------------------

@app.post("/api/campuses")
@require_roles("PlatformAdmin")
def create_campus():
    data = body()
    require_fields(data, ["name", "jurisdiction_code",
                          "jurisdiction_registration_number",
                          "medical_director_id", "response_time_target_seconds"])
    name = req_str(data, "name")
    jurisdiction_code = req_str(data, "jurisdiction_code")
    reg_num = data["jurisdiction_registration_number"]
    if not isinstance(reg_num, str):
        invalid_request("jurisdiction_registration_number must be a string")
    md_id = data["medical_director_id"]
    if not isinstance(md_id, str):
        invalid_request("medical_director_id must be a string")
    target = req_int(data, "response_time_target_seconds")
    campus = new_entity()
    campus.update({
        "name": name,
        "jurisdiction_code": jurisdiction_code,
        "jurisdiction_registration_number": reg_num,
        "medical_director_id": md_id,
        "response_time_target_seconds": target,
        "readiness_posture": "OPERATIONAL",
    })
    db.campuses[campus["id"]] = campus
    return success(campus, status=201)


@app.get("/api/campuses/<campusId>")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector",
               "Inspector", "Responder")
def get_campus(campusId):
    sweep_all(db.now())
    return success(get_campus_or_404(campusId))


@app.get("/api/campuses")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def list_campuses():
    limit, offset = pagination_params()
    sweep_all(db.now())
    page, meta = paginate(list(db.campuses.values()), limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.get("/api/campuses/<campusId>/coverage-report")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector")
def coverage_report(campusId):
    campus = get_campus_or_404(campusId)
    zones = sorted(
        (z for z in db.zones.values() if z["campus_id"] == campusId),
        key=lambda z: (z["created_at"], z["id"]),
    )
    target = campus["response_time_target_seconds"]
    per_zone = []
    covered_sum = 0
    for zone in zones:
        speed = Decimal(str(zone["avg_walk_speed_mps"]))
        elevator = int(zone["elevator_delay_seconds"]) if zone["requires_elevator"] else 0
        cabinets = sorted(
            (c for c in db.cabinets.values() if c["zone_id"] == zone["id"]),
            key=lambda c: (c["created_at"], c["id"]),
        )
        best_pess = None
        best_opt = None
        best_cab = None
        for cab in cabinets:
            dx = abs(Decimal(str(cab["centroid_x_m"])))
            dy = abs(Decimal(str(cab["centroid_y_m"])))
            euclid = (dx * dx + dy * dy).sqrt()
            manhattan = (dx + dy) * Decimal("1.30")
            opt = int((euclid / speed).quantize(Decimal("1"),
                                                rounding=ROUND_HALF_UP)) + elevator
            pess = int((manhattan / speed).quantize(Decimal("1"),
                                                    rounding=ROUND_HALF_UP)) + elevator
            if best_pess is None or pess < best_pess:
                best_pess, best_opt, best_cab = pess, opt, cab["id"]
        if best_cab is None:
            covered = 0
            entry = {
                "zone_id": zone["id"],
                "zone_code": zone["zone_code"],
                "cabinet_id": None,
                "optimistic_response_time_seconds": None,
                "pessimistic_response_time_seconds": None,
                "covered": 0,
            }
        else:
            covered = 1 if best_pess <= target else 0
            entry = {
                "zone_id": zone["id"],
                "zone_code": zone["zone_code"],
                "cabinet_id": best_cab,
                "optimistic_response_time_seconds": best_opt,
                "pessimistic_response_time_seconds": best_pess,
                "covered": covered,
            }
        covered_sum += covered
        per_zone.append(entry)
    total = len(zones)
    if total == 0:
        coverage_pct = 0
    else:
        coverage_pct = int(
            (Decimal(covered_sum * 100) / Decimal(total)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
        )
    return success({"coverage_pct": coverage_pct, "per_zone": per_zone})


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@app.post("/api/zones")
@require_roles("ProgramManager")
def create_zone():
    data = body()
    require_fields(data, ["campus_id", "zone_code", "floor_area_sqm",
                          "avg_walk_speed_mps", "requires_elevator",
                          "elevator_delay_seconds"])
    campus = get_campus_or_404(data["campus_id"])
    zone = new_entity()
    zone.update({
        "campus_id": campus["id"],
        "zone_code": req_str(data, "zone_code"),
        "floor_area_sqm": req_int(data, "floor_area_sqm"),
        "avg_walk_speed_mps": req_number(data, "avg_walk_speed_mps"),
        "requires_elevator": req_bool(data, "requires_elevator"),
        "elevator_delay_seconds": req_int(data, "elevator_delay_seconds"),
    })
    db.zones[zone["id"]] = zone
    return success(zone, status=201)


@app.get("/api/zones/<zoneId>")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def get_zone(zoneId):
    return success(get_zone_or_404(zoneId))


@app.get("/api/zones")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def list_zones():
    limit, offset = pagination_params()
    items = list(db.zones.values())
    campus_id = request.args.get("campus_id")
    if campus_id is not None:
        items = [z for z in items if z["campus_id"] == campus_id]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Device models
# ---------------------------------------------------------------------------

@app.post("/api/device-models")
@require_roles("PlatformAdmin")
def create_device_model():
    data = body()
    require_fields(data, ["model_code", "manufacturer",
                          "pad_shelf_life_months", "battery_shelf_life_months",
                          "prescription_required"])
    model = new_entity()
    model.update({
        "model_code": req_str(data, "model_code"),
        "manufacturer": req_str(data, "manufacturer"),
        "pad_shelf_life_months": req_int(data, "pad_shelf_life_months"),
        "battery_shelf_life_months": req_int(data, "battery_shelf_life_months"),
        "prescription_required": req_bool(data, "prescription_required"),
    })
    db.device_models[model["id"]] = model
    return success(model, status=201)


@app.get("/api/device-models/<deviceModelId>")
@require_roles("PlatformAdmin", "ProgramManager")
def get_device_model(deviceModelId):
    return success(get_model_or_404(deviceModelId))


# ---------------------------------------------------------------------------
# Cabinets
# ---------------------------------------------------------------------------

@app.post("/api/cabinets")
@require_roles("ProgramManager")
def create_cabinet():
    data = body()
    require_fields(data, ["zone_id", "location_label",
                          "centroid_x_m", "centroid_y_m"])
    zone = get_zone_or_404(data["zone_id"])
    cab = new_entity()
    cab.update({
        "zone_id": zone["id"],
        "location_label": req_str(data, "location_label"),
        "centroid_x_m": req_number(data, "centroid_x_m"),
        "centroid_y_m": req_number(data, "centroid_y_m"),
        "installed_device_id": None,
        "status": "EMPTY",
    })
    db.cabinets[cab["id"]] = cab
    return success(cab, status=201)


@app.get("/api/cabinets/<cabinetId>")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def get_cabinet(cabinetId):
    return success(get_cabinet_or_404(cabinetId))


@app.get("/api/cabinets")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def list_cabinets():
    limit, offset = pagination_params()
    items = list(db.cabinets.values())
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    if zone_id is not None:
        items = [c for c in items if c["zone_id"] == zone_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/cabinets/<cabinetId>/open")
@require_roles("Anonymous")
def open_cabinet(cabinetId):
    cab = get_cabinet_or_404(cabinetId)
    device = db.devices.get(cab["installed_device_id"] or "")
    if device is None or device["status"] != "IN_SERVICE":
        invalid_state("Cabinet does not hold an installed in-service device")
    zone = get_zone_or_404(cab["zone_id"])
    now = db.now()

    event = new_entity()
    event.update({
        "campus_id": device["campus_id"],
        "cabinet_id": cab["id"],
        "device_id": device["id"],
        "opened_at": ts_now(),
        "closed_at": None,
        "hospital_code": None,
        "patient_transported": None,
        "pads_consumed": False,
        "first_responder_id": None,
        "status": "OPEN",
    })
    db.emergency_events[event["id"]] = event

    cab["status"] = "ALARM_OPEN"
    touch(cab)
    device["status"] = "POST_EVENT"
    touch(device)
    recompute_device_and_campus(device, now)
    return success(event, status=201)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@app.post("/api/devices")
@require_roles("ProgramManager")
def create_device():
    data = body()
    require_fields(data, ["campus_id", "device_model_id", "serial_number"])
    campus = get_campus_or_404(data["campus_id"])
    model = get_model_or_404(data["device_model_id"])
    serial = req_str(data, "serial_number")
    for d in db.devices.values():
        if d["campus_id"] == campus["id"] and d["serial_number"] == serial \
                and d["status"] != "DECOMMISSIONED":
            raise_err(ERR_SERIAL_NUMBER_CONFLICT,
                      "serial_number already registered on this campus")
    prescription_number = data.get("prescription_number")
    if prescription_number is not None and not isinstance(prescription_number, str):
        invalid_request("prescription_number must be a string")
    device = new_entity()
    device.update({
        "campus_id": campus["id"],
        "device_model_id": model["id"],
        "serial_number": serial,
        "cabinet_id": None,
        "prescription_number": prescription_number or "",
        "current_pad_install_id": None,
        "current_battery_install_id": None,
        "last_inspection_at": None,
        "last_selftest_status": "UNKNOWN",
        "last_selftest_reported_at": None,
        "inspection_latched": False,
        "readiness_posture": "OUT_OF_SERVICE",
        "status": "REGISTERED",
    })
    db.devices[device["id"]] = device
    refresh_campus_posture(campus["id"], db.now())
    return success(device, status=201)


@app.get("/api/devices/<deviceId>")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector", "MedicalDirector")
def get_device(deviceId):
    return success(device_fresh(deviceId))


@app.get("/api/devices")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector", "MedicalDirector")
def list_devices():
    limit, offset = pagination_params()
    sweep_all(db.now())
    items = list(db.devices.values())
    for param in ("campus_id", "cabinet_id", "device_model_id",
                  "status", "readiness_posture"):
        value = request.args.get(param)
        if value is not None:
            if param == "cabinet_id" and value == "null":
                items = [d for d in items if d["cabinet_id"] is None]
            else:
                items = [d for d in items if d[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/devices/<deviceId>/install")
@require_roles("ProgramManager")
def install_device(deviceId):
    data = body()
    device = device_fresh(deviceId)
    require_fields(data, ["cabinet_id"])
    cab = get_cabinet_or_404(data["cabinet_id"])
    check_occ(device, data)
    if device["status"] != "REGISTERED":
        invalid_state("Device must be REGISTERED to install")
    model = get_model_or_404(device["device_model_id"])
    if model["prescription_required"] and not device.get("prescription_number"):
        raise_err(ERR_PRESCRIPTION_REQUIRED,
                  "Device model requires an active prescription")
    zone = get_zone_or_404(cab["zone_id"])
    if zone["campus_id"] != device["campus_id"]:
        raise_err(ERR_INCOMPATIBLE_REFERENCE,
                  "Cabinet is not in a zone under the device's campus")
    if cab["status"] != "EMPTY":
        raise_err(ERR_CABINET_NOT_EMPTY, "Cabinet is not EMPTY")
    now = db.now()
    device["status"] = "INSTALLED"
    device["cabinet_id"] = cab["id"]
    touch(device)
    cab["status"] = "OCCUPIED"
    cab["installed_device_id"] = device["id"]
    touch(cab)
    recompute_device_and_campus(device, now)
    return success(device)


@app.post("/api/devices/<deviceId>/commission")
@require_roles("ProgramManager")
def commission_device(deviceId):
    device = device_fresh(deviceId)
    if device["status"] != "INSTALLED":
        invalid_state("Device must be INSTALLED to commission")
    model = get_model_or_404(device["device_model_id"])
    if model["prescription_required"] and not device.get("prescription_number"):
        raise_err(ERR_PRESCRIPTION_REQUIRED,
                  "Device model requires an active prescription")
    if device["readiness_posture"] != "READY":
        raise_err(ERR_DEVICE_NOT_READY,
                  "Device readiness_posture is not READY")
    device["status"] = "IN_SERVICE"
    touch(device)
    refresh_campus_posture(device["campus_id"], db.now())
    return success(device)


@app.post("/api/devices/<deviceId>/send_to_maintenance")
@require_roles("ProgramManager")
def send_to_maintenance(deviceId):
    device = device_fresh(deviceId)
    if device["status"] not in ("INSTALLED", "POST_EVENT"):
        invalid_state("Device cannot be sent to maintenance from its current state")
    if device["status"] == "POST_EVENT":
        for e in db.emergency_events.values():
            if e["device_id"] == device["id"] and \
                    e["status"] not in ("RESOLVED", "CASE_REVIEW", "CLOSED"):
                raise_err(ERR_DEVICE_IN_EVENT,
                          "Device has an emergency event that is not yet resolved")
    if device["cabinet_id"]:
        cab = db.cabinets.get(device["cabinet_id"])
        if cab is not None:
            cab["status"] = "EMPTY"
            cab["installed_device_id"] = None
            touch(cab)
        device["cabinet_id"] = None
    device["status"] = "MAINTENANCE"
    touch(device)
    recompute_device_and_campus(device, db.now())
    return success(device)


@app.post("/api/devices/<deviceId>/return_to_service")
@require_roles("Inspector")
def return_to_service(deviceId):
    device = device_fresh(deviceId)
    if device["status"] != "MAINTENANCE":
        invalid_state("Device must be in MAINTENANCE to return to service")
    now = db.now()
    inspections = [i for i in db.inspections.values()
                   if i["device_id"] == device["id"] and i["completed_at"]]
    latest = None
    for insp in inspections:
        comp = parse_dt(insp["completed_at"], "completed_at")
        if latest is None or comp > latest[1]:
            latest = (insp, comp)
    if latest is None or latest[0]["outcome"] != "PASS" or \
            now > latest[1] + timedelta(days=30):
        raise_err(ERR_DEVICE_NOT_READY,
                  "No passing inspection within the last 30 days")
    for order in db.replenishment_orders.values():
        if order["status"] != "PENDING":
            continue
        if order.get("emergency_event_id"):
            ev = db.emergency_events.get(order["emergency_event_id"])
            if ev is not None and ev["device_id"] == device["id"]:
                raise_err(ERR_INVALID_STATE,
                          "Device has unresolved PENDING replenishment orders")
    if device["readiness_posture"] != "READY":
        raise_err(ERR_DEVICE_NOT_READY,
                  "Device readiness_posture is not READY")
    device["status"] = "INSTALLED"
    touch(device)
    recompute_device_and_campus(device, now)
    return success(device)


@app.post("/api/devices/<deviceId>/decommission")
@require_roles("ProgramManager")
def decommission_device(deviceId):
    device = device_fresh(deviceId)
    if device["status"] not in ("REGISTERED", "MAINTENANCE"):
        invalid_state("Device cannot be decommissioned from its current state")
    if device["status"] == "MAINTENANCE":
        for e in db.emergency_events.values():
            if e["device_id"] == device["id"] and \
                    e["status"] in ("OPEN", "RESPONDING"):
                raise_err(ERR_DEVICE_IN_EVENT,
                          "Device has open emergency events")
    if device["cabinet_id"]:
        cab = db.cabinets.get(device["cabinet_id"])
        if cab is not None:
            cab["status"] = "EMPTY"
            cab["installed_device_id"] = None
            touch(cab)
        device["cabinet_id"] = None
    device["status"] = "DECOMMISSIONED"
    touch(device)
    recompute_device_and_campus(device, db.now())
    return success(device)


# ---------------------------------------------------------------------------
# Consumable lots
# ---------------------------------------------------------------------------

@app.post("/api/consumable-lots")
@require_roles("ProgramManager")
def create_lot():
    data = body()
    require_fields(data, ["campus_id", "device_model_id", "kind", "lot_code",
                          "manufacturer_expires_at", "quantity_received"])
    campus = get_campus_or_404(data["campus_id"])
    model = get_model_or_404(data["device_model_id"])
    kind = req_enum(data, "kind", ["PAD", "BATTERY"])
    mfg = parse_dt(data["manufacturer_expires_at"], "manufacturer_expires_at")
    qty = req_int(data, "quantity_received")
    lot = new_entity()
    lot.update({
        "campus_id": campus["id"],
        "device_model_id": model["id"],
        "kind": kind,
        "lot_code": req_str(data, "lot_code"),
        "manufacturer_expires_at": fmt_dt(mfg),
        "quantity_received": qty,
        "quantity_available": qty,
    })
    db.consumable_lots[lot["id"]] = lot
    return success(lot, status=201)


@app.get("/api/consumable-lots/<lotId>")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def get_lot(lotId):
    return success(get_lot_or_404(lotId))


@app.get("/api/consumable-lots")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def list_lots():
    limit, offset = pagination_params()
    items = list(db.consumable_lots.values())
    for param in ("campus_id", "device_model_id", "kind"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Installs
# ---------------------------------------------------------------------------

@app.post("/api/installs")
@require_roles("ProgramManager")
def create_install():
    data = body()
    require_fields(data, ["device_id", "consumable_lot_id"])
    device = device_fresh(data["device_id"])
    lot = get_lot_or_404(data["consumable_lot_id"])
    check_occ(device, data)
    if device["status"] == "DECOMMISSIONED":
        invalid_state("Device is decommissioned")
    model = get_model_or_404(device["device_model_id"])
    if lot["device_model_id"] != model["id"]:
        raise_err(ERR_INCOMPATIBLE_REFERENCE,
                  "Lot is not compatible with the device's model")
    now = db.now()
    if lot["quantity_available"] <= 0 or \
            parse_dt(lot["manufacturer_expires_at"], "manufacturer_expires_at") <= now:
        raise_err(ERR_LOT_UNAVAILABLE, "Lot is empty or expired")

    kind = lot["kind"]
    shelf_months = model["pad_shelf_life_months"] if kind == "PAD" \
        else model["battery_shelf_life_months"]
    shelf_end = add_months(now, shelf_months)
    mfg = parse_dt(lot["manufacturer_expires_at"], "manufacturer_expires_at")
    expires_at = min(mfg, shelf_end)

    inst = new_entity()
    inst.update({
        "device_id": device["id"],
        "consumable_lot_id": lot["id"],
        "kind": kind,
        "installed_at": fmt_dt(now),
        "expires_at": fmt_dt(expires_at),
        "base_expires_at": fmt_dt(expires_at),
        "removed_at": None,
        "disposition": "ACTIVE",
    })
    db.installs[inst["id"]] = inst

    lot["quantity_available"] -= 1
    touch(lot)

    field = "current_pad_install_id" if kind == "PAD" else "current_battery_install_id"
    prior_id = device.get(field)
    if prior_id:
        prior = db.installs.get(prior_id)
        if prior is not None and prior["disposition"] == "ACTIVE":
            prior["disposition"] = "REPLACED"
            prior["removed_at"] = ts_now()
            touch(prior)
    device[field] = inst["id"]
    touch(device)
    recompute_device_and_campus(device, now)
    return success(inst, status=201)


@app.get("/api/installs/<installId>")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def get_install(installId):
    return success(get_install_or_404(installId))


@app.get("/api/installs")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def list_installs():
    limit, offset = pagination_params()
    sweep_all(db.now())
    items = list(db.installs.values())
    for param in ("device_id", "consumable_lot_id", "kind", "disposition"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/installs/<installId>/remove")
@require_roles("ProgramManager")
def remove_install(installId):
    inst = get_install_or_404(installId)
    if inst["disposition"] != "ACTIVE":
        invalid_state("Install is not ACTIVE")
    inst["disposition"] = "EXPIRED_REMOVED"
    inst["removed_at"] = ts_now()
    touch(inst)
    device = get_device_or_404(inst["device_id"])
    field = "current_pad_install_id" if inst["kind"] == "PAD" \
        else "current_battery_install_id"
    if device.get(field) == inst["id"]:
        device[field] = None
        touch(device)
    recompute_device_and_campus(device, db.now())
    return success(inst)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

@app.post("/api/inspections")
@require_roles("Inspector")
def create_inspection():
    data = body()
    require_fields(data, ["device_id", "inspector_id", "scheduled_for"])
    device = get_device_or_404(data["device_id"])
    inspector = get_responder_or_404(data["inspector_id"])
    sched = parse_dt(data["scheduled_for"], "scheduled_for")
    insp = new_entity()
    insp.update({
        "device_id": device["id"],
        "inspector_id": inspector["id"],
        "scheduled_for": fmt_dt(sched),
        "completed_at": None,
        "checklist_items": None,
        "outcome": "SCHEDULED",
        "fail_reason": None,
    })
    db.inspections[insp["id"]] = insp
    return success(insp, status=201)


@app.get("/api/inspections/<inspectionId>")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def get_inspection(inspectionId):
    insp = get_inspection_or_404(inspectionId)
    sweep_device_time_based(insp["device_id"], db.now())
    return success(insp)


@app.get("/api/inspections")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def list_inspections():
    limit, offset = pagination_params()
    sweep_all(db.now())
    items = list(db.inspections.values())
    for param in ("device_id", "inspector_id", "outcome"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/inspections/<inspectionId>/submit")
@require_roles("Inspector")
def submit_inspection(inspectionId):
    insp = get_inspection_or_404(inspectionId)
    if insp["outcome"] != "SCHEDULED":
        invalid_state("Inspection is not SCHEDULED")
    device = get_device_or_404(insp["device_id"])
    if device["status"] == "DECOMMISSIONED":
        invalid_state("Device is decommissioned")
    data = body()
    now = db.now()
    sched = parse_dt(insp["scheduled_for"], "scheduled_for")
    if now < sched:
        raise_err(ERR_TEMPORAL_WINDOW_VIOLATION,
                  "Inspection window has not opened")
    if now > sched + timedelta(days=7):
        raise_err(ERR_INSPECTION_OVERDUE,
                  "Inspection window closed (scheduled_for + 7 days)")
    items = data.get("checklist_items")
    if not isinstance(items, list) or len(items) == 0:
        raise_err(ERR_INSPECTION_CHECKLIST_INCOMPLETE,
                  "checklist_items is required and must be a non-empty list")
    for entry in items:
        if not isinstance(entry, dict) or \
                not isinstance(entry.get("item_code"), str) or \
                not entry.get("item_code") or \
                entry.get("result") not in ("PASS", "FAIL"):
            raise_err(ERR_INSPECTION_CHECKLIST_INCOMPLETE,
                      "Each checklist item must pair an item_code with a result of PASS or FAIL")
    any_fail = any(e["result"] == "FAIL" for e in items)
    fail_reason = data.get("fail_reason")
    if any_fail and (not isinstance(fail_reason, str) or not fail_reason):
        raise_err(ERR_INSPECTION_CHECKLIST_INCOMPLETE,
                  "fail_reason is required when any checklist item fails")

    insp["checklist_items"] = items
    insp["completed_at"] = ts_now()
    insp["outcome"] = "FAIL" if any_fail else "PASS"
    insp["fail_reason"] = fail_reason if any_fail else None
    touch(insp)

    device = device_fresh(device["id"])
    device["last_inspection_at"] = insp["completed_at"]
    # A failed inspection latches the device OUT_OF_SERVICE until a later
    # passing inspection restores it (§3.3).
    device["inspection_latched"] = bool(any_fail)
    touch(device)
    recompute_device_and_campus(device, now)
    return success(insp)


# ---------------------------------------------------------------------------
# Self-test reports
# ---------------------------------------------------------------------------

@app.post("/api/self-test-reports")
@require_roles("System")
def create_self_test_report():
    data = body()
    require_fields(data, ["device_id", "reported_at", "result"])
    device = get_device_or_404(data["device_id"])
    reported = parse_dt(data["reported_at"], "reported_at")
    result = req_enum(data, "result", ["PASS", "FAIL"])
    fault = data.get("fault_code")
    if fault is not None and not isinstance(fault, str):
        invalid_request("fault_code must be a string")
    report = {
        "id": new_id(),
        "created_at": ts_now(),
        "device_id": device["id"],
        "reported_at": fmt_dt(reported),
        "result": result,
        "fault_code": fault,
    }
    db.self_test_reports[report["id"]] = report

    device = device_fresh(device["id"])
    device["last_selftest_status"] = result
    device["last_selftest_reported_at"] = report["reported_at"]
    batt_id = device.get("current_battery_install_id")
    batt = db.installs.get(batt_id or "")
    if result == "FAIL" and isinstance(fault, str) and fault.startswith("BATT-"):
        # Battery expires immediately regardless of dates (§3.2 battery rule).
        if batt is not None and batt["disposition"] == "ACTIVE":
            batt["expires_at"] = fmt_dt(db.now())
            touch(batt)
    elif result == "PASS":
        # A passing self-test restores a battery whose immediate expiry was
        # driven solely by a prior BATT- fault report.
        if batt is not None and batt["disposition"] == "ACTIVE" and \
                batt.get("base_expires_at") and \
                batt["expires_at"] != batt["base_expires_at"]:
            batt["expires_at"] = batt["base_expires_at"]
            touch(batt)
    touch(device)
    recompute_device_and_campus(device, db.now())
    return success(report, status=201)


@app.get("/api/self-test-reports")
@require_roles("PlatformAdmin", "ProgramManager", "Inspector")
def list_self_test_reports():
    limit, offset = pagination_params()
    items = list(db.self_test_reports.values())
    for param in ("device_id", "result"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Responders
# ---------------------------------------------------------------------------

@app.post("/api/responders")
@require_roles("ProgramManager")
def create_responder():
    data = body()
    require_fields(data, ["campus_id", "full_name", "badge_number",
                          "responder_role"])
    campus = get_campus_or_404(data["campus_id"])
    role = req_enum(data, "responder_role",
                    ["LAY_RESPONDER", "MEDICAL_DIRECTOR",
                     "PROGRAM_MANAGER", "INSPECTOR"])
    responder = new_entity()
    responder.update({
        "campus_id": campus["id"],
        "full_name": req_str(data, "full_name"),
        "badge_number": req_str(data, "badge_number"),
        "responder_role": role,
        "certified_through": None,
        "status": "ACTIVE",
    })
    db.responders[responder["id"]] = responder
    return success(responder, status=201)


@app.get("/api/responders/<responderId>")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def get_responder(responderId):
    return success(get_responder_or_404(responderId))


@app.get("/api/responders")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def list_responders():
    limit, offset = pagination_params()
    items = list(db.responders.values())
    for param in ("campus_id", "responder_role", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Training sessions
# ---------------------------------------------------------------------------

@app.post("/api/training-sessions")
@require_roles("ProgramManager")
def create_training_session():
    data = body()
    require_fields(data, ["campus_id", "instructor_id", "starts_at",
                          "ends_at", "capacity",
                          "certification_months_granted"])
    campus = get_campus_or_404(data["campus_id"])
    instructor = get_responder_or_404(data["instructor_id"])
    now = db.now()
    starts = parse_dt(data["starts_at"], "starts_at")
    ends = parse_dt(data["ends_at"], "ends_at")
    if ends <= starts or starts <= now:
        raise_err(ERR_TEMPORAL_WINDOW_VIOLATION,
                  "ends_at must be later than starts_at and starts_at must be in the future")
    if instructor["responder_role"] not in ("MEDICAL_DIRECTOR", "PROGRAM_MANAGER"):
        raise_err(ERR_INSTRUCTOR_ROLE_INVALID,
                  "Instructor must be a MEDICAL_DIRECTOR or PROGRAM_MANAGER")
    session = new_entity()
    session.update({
        "campus_id": campus["id"],
        "instructor_id": instructor["id"],
        "starts_at": fmt_dt(starts),
        "ends_at": fmt_dt(ends),
        "capacity": req_int(data, "capacity"),
        "certification_months_granted": req_int(data, "certification_months_granted"),
        "status": "SCHEDULED",
        "attendees": [],
    })
    db.training_sessions[session["id"]] = session
    return success(session, status=201)


@app.get("/api/training-sessions/<sessionId>")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def get_training_session(sessionId):
    return success(get_session_or_404(sessionId))


@app.get("/api/training-sessions")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def list_training_sessions():
    limit, offset = pagination_params()
    items = list(db.training_sessions.values())
    for param in ("campus_id", "instructor_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/training-sessions/<sessionId>/enroll")
@require_roles("ProgramManager")
def enroll_training_session(sessionId):
    session = get_session_or_404(sessionId)
    data = body()
    require_fields(data, ["responder_id"])
    responder = get_responder_or_404(data["responder_id"])
    now = db.now()
    if session["status"] != "SCHEDULED":
        invalid_state("Training session is not SCHEDULED")
    if now >= parse_dt(session["starts_at"], "starts_at"):
        raise_err(ERR_SESSION_ALREADY_STARTED,
                  "Enrollment is closed once the session has started")
    if len(session["attendees"]) >= session["capacity"]:
        raise_err(ERR_TRAINING_FULL, "Training session is at capacity")
    session["attendees"].append({
        "responder_id": responder["id"],
        "created_at": ts_now(),
        "seq": len(session["attendees"]),
    })
    touch(session)
    return success(session)


@app.post("/api/training-sessions/<sessionId>/complete")
@require_roles("ProgramManager")
def complete_training_session(sessionId):
    session = get_session_or_404(sessionId)
    data = body()
    require_fields(data, ["attendee_ids"])
    attendee_ids = data["attendee_ids"]
    if not isinstance(attendee_ids, list) or len(attendee_ids) == 0:
        invalid_request("attendee_ids must be a non-empty list")
    now = db.now()
    if session["status"] != "SCHEDULED":
        invalid_state("Training session is not SCHEDULED")
    if now < parse_dt(session["ends_at"], "ends_at"):
        raise_err(ERR_SESSION_NOT_ENDED,
                  "Session cannot be completed before ends_at")
    enrolled = [a["responder_id"] for a in session["attendees"]]
    order_index = {rid: idx for idx, rid in enumerate(enrolled)}
    attendees = []
    for rid in attendee_ids:
        if not isinstance(rid, str):
            invalid_request("attendee_ids must be strings")
        responder = get_responder_or_404(rid)
        if rid not in order_index:
            invalid_request("attendee is not enrolled in this session")
        attendees.append((order_index[rid], responder))
    attendees.sort(key=lambda t: t[0])

    session["status"] = "COMPLETED"
    touch(session)
    ends = parse_dt(session["ends_at"], "ends_at")
    months = session["certification_months_granted"]
    for _idx, responder in attendees:
        current = responder.get("certified_through")
        base = ends if current is None else max(parse_dt(current, "certified_through"), ends)
        responder["certified_through"] = fmt_dt(add_months(base, months))
        touch(responder)
    return success(session)


@app.post("/api/training-sessions/<sessionId>/cancel")
@require_roles("ProgramManager")
def cancel_training_session(sessionId):
    session = get_session_or_404(sessionId)
    if session["status"] != "SCHEDULED":
        invalid_state("Training session is not SCHEDULED")
    if db.now() >= parse_dt(session["starts_at"], "starts_at"):
        raise_err(ERR_SESSION_ALREADY_STARTED,
                  "Cannot cancel a session that has started")
    session["status"] = "CANCELLED"
    touch(session)
    return success(session)


# ---------------------------------------------------------------------------
# Emergency events
# ---------------------------------------------------------------------------

@app.get("/api/emergency-events/<eventId>")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Responder")
def get_event(eventId):
    return success(get_event_or_404(eventId))


@app.get("/api/emergency-events")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector", "Inspector")
def list_events():
    limit, offset = pagination_params()
    items = list(db.emergency_events.values())
    for param in ("campus_id", "cabinet_id", "device_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


def _caller_responder():
    user_id = request.headers.get("X-User-ID")
    return get_responder_or_404(user_id)


def _check_certified(responder, now):
    cert = responder.get("certified_through")
    if responder["status"] != "ACTIVE" or cert is None or \
            parse_dt(cert, "certified_through") <= now:
        raise_err(ERR_RESPONDER_NOT_CERTIFIED,
                  "Responder is not currently certified")


@app.post("/api/emergency-events/<eventId>/acknowledge")
@require_roles("Responder")
def acknowledge_event(eventId):
    event = get_event_or_404(eventId)
    responder = _caller_responder()
    now = db.now()
    if event["status"] != "OPEN":
        raise_err(ERR_EVENT_ALREADY_ACKED,
                  "Emergency event has already been acknowledged")
    _check_certified(responder, now)
    event["status"] = "RESPONDING"
    event["first_responder_id"] = responder["id"]
    touch(event)
    return success(event)


@app.post("/api/emergency-events/<eventId>/resolve")
@require_roles("Responder")
def resolve_event(eventId):
    event = get_event_or_404(eventId)
    responder = _caller_responder()
    now = db.now()
    if event["status"] != "RESPONDING":
        raise_err(ERR_EVENT_NOT_RESPONDING,
                  "Emergency event is not in RESPONDING")
    _check_certified(responder, now)
    data = body()
    require_fields(data, ["hospital_code", "patient_transported",
                          "pads_consumed"])
    hospital_code = req_str(data, "hospital_code")
    patient_transported = req_bool(data, "patient_transported")
    pads_consumed = req_bool(data, "pads_consumed")

    event["hospital_code"] = hospital_code
    event["patient_transported"] = patient_transported
    event["pads_consumed"] = pads_consumed
    event["status"] = "RESOLVED"
    event["closed_at"] = ts_now()
    touch(event)

    cab = db.cabinets.get(event["cabinet_id"])
    if cab is not None:
        cab["status"] = "OCCUPIED"
        touch(cab)

    device = get_device_or_404(event["device_id"])
    if pads_consumed:
        pad_id = device.get("current_pad_install_id")
        pad = db.installs.get(pad_id or "")
        if pad is not None and pad["disposition"] == "ACTIVE":
            pad["disposition"] = "CONSUMED_IN_EVENT"
            pad["removed_at"] = ts_now()
            touch(pad)
        if device.get("current_pad_install_id"):
            device["current_pad_install_id"] = None
        order = new_entity()
        order.update({
            "campus_id": event["campus_id"],
            "emergency_event_id": event["id"],
            "kind": "PAD",
            "quantity": 1,
            "status": "PENDING",
            "received_lot_id": None,
        })
        db.replenishment_orders[order["id"]] = order
    touch(device)
    recompute_device_and_campus(device, now)
    return success(event)


@app.post("/api/emergency-events/<eventId>/close_no_patient")
@require_roles("Responder")
def close_event_no_patient(eventId):
    event = get_event_or_404(eventId)
    responder = _caller_responder()
    now = db.now()
    if event["status"] != "OPEN":
        invalid_state("Only an OPEN event can be closed without a patient")
    _check_certified(responder, now)
    event["status"] = "CLOSED"
    event["closed_at"] = ts_now()
    touch(event)

    cab = db.cabinets.get(event["cabinet_id"])
    if cab is not None:
        cab["status"] = "OCCUPIED"
        touch(cab)
    device = get_device_or_404(event["device_id"])
    device["status"] = "IN_SERVICE"
    touch(device)
    recompute_device_and_campus(device, now)
    return success(event)


# ---------------------------------------------------------------------------
# Case reviews
# ---------------------------------------------------------------------------

@app.post("/api/case-reviews")
@require_roles("MedicalDirector")
def create_case_review():
    data = body()
    require_fields(data, ["emergency_event_id", "reviewer_id",
                          "hospital_reviewer_name", "device_data_retrieved",
                          "outcome_code", "notes"])
    event = get_event_or_404(data["emergency_event_id"])
    reviewer = get_responder_or_404(data["reviewer_id"])
    if event["status"] != "RESOLVED":
        invalid_state("Emergency event must be RESOLVED before case review")
    campus = get_campus_or_404(event["campus_id"])
    if reviewer["responder_role"] != "MEDICAL_DIRECTOR" or \
            reviewer["id"] == campus["medical_director_id"]:
        raise_err(ERR_MEDICAL_DIRECTION_CONFLICT,
                  "Reviewer must be a medical director other than the campus medical director")
    outcome = req_enum(data, "outcome_code",
                       ["SURVIVED_TO_DISCHARGE", "SURVIVED_TO_ADMISSION",
                        "DECEASED", "NO_SHOCK_INDICATED"])
    review = new_entity()
    review.update({
        "emergency_event_id": event["id"],
        "reviewer_id": reviewer["id"],
        "hospital_reviewer_name": req_str(data, "hospital_reviewer_name"),
        "device_data_retrieved": req_bool(data, "device_data_retrieved"),
        "outcome_code": outcome,
        "notes": data["notes"] if isinstance(data["notes"], str) else None,
        "status": "DRAFT",
    })
    db.case_reviews[review["id"]] = review
    event["status"] = "CASE_REVIEW"
    touch(event)
    return success(review, status=201)


@app.get("/api/case-reviews/<reviewId>")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector")
def get_case_review(reviewId):
    return success(get_review_or_404(reviewId))


@app.get("/api/case-reviews")
@require_roles("PlatformAdmin", "ProgramManager", "MedicalDirector")
def list_case_reviews():
    limit, offset = pagination_params()
    items = list(db.case_reviews.values())
    for param in ("emergency_event_id", "reviewer_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/case-reviews/<reviewId>/submit")
@require_roles("MedicalDirector")
def submit_case_review(reviewId):
    review = get_review_or_404(reviewId)
    if review["status"] != "DRAFT":
        invalid_state("Only a DRAFT review can be submitted")
    if not review.get("outcome_code") or \
            not review.get("hospital_reviewer_name") or \
            not isinstance(review.get("device_data_retrieved"), bool):
        raise_err(ERR_CASE_REVIEW_INCOMPLETE,
                  "outcome_code, hospital_reviewer_name and device_data_retrieved are all required")
    review["status"] = "SUBMITTED"
    touch(review)
    return success(review)


@app.post("/api/case-reviews/<reviewId>/accept")
@require_roles("MedicalDirector")
def accept_case_review(reviewId):
    review = get_review_or_404(reviewId)
    if review["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED review can be accepted")
    caller = _caller_responder()
    if caller["id"] == review["reviewer_id"] or \
            caller["responder_role"] != "MEDICAL_DIRECTOR":
        raise_err(ERR_MEDICAL_DIRECTION_CONFLICT,
                  "Acceptor must be a different medical director from the reviewer")
    if review.get("device_data_retrieved") is not True:
        raise_err(ERR_CASE_REVIEW_INCOMPLETE,
                  "device_data_retrieved must be true before acceptance")
    review["status"] = "ACCEPTED"
    touch(review)
    event = get_event_or_404(review["emergency_event_id"])
    if event["status"] == "CASE_REVIEW":
        event["status"] = "CLOSED"
        touch(event)
    return success(review)


@app.post("/api/case-reviews/<reviewId>/reopen")
@require_roles("MedicalDirector")
def reopen_case_review(reviewId):
    review = get_review_or_404(reviewId)
    if review["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED review can be reopened")
    review["status"] = "DRAFT"
    touch(review)
    return success(review)


# ---------------------------------------------------------------------------
# Replenishment orders
# ---------------------------------------------------------------------------

@app.get("/api/replenishment-orders/<orderId>")
@require_roles("PlatformAdmin", "ProgramManager")
def get_order(orderId):
    return success(get_order_or_404(orderId))


@app.get("/api/replenishment-orders")
@require_roles("PlatformAdmin", "ProgramManager")
def list_orders():
    limit, offset = pagination_params()
    items = list(db.replenishment_orders.values())
    for param in ("campus_id", "emergency_event_id", "received_lot_id",
                  "status"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    page, meta = paginate(items, limit, offset)
    return success(page, response_type="array", pagination=meta)


@app.post("/api/replenishment-orders/<orderId>/receive")
@require_roles("ProgramManager")
def receive_order(orderId):
    order = get_order_or_404(orderId)
    data = body()
    lot_code = data.get("lot_code")
    mfg_raw = data.get("manufacturer_expires_at")
    if order["status"] != "PENDING":
        raise_err(ERR_REPLENISHMENT_INVALID, "Order is not PENDING")
    if not isinstance(lot_code, str) or not lot_code or \
            not isinstance(mfg_raw, str) or not mfg_raw:
        raise_err(ERR_REPLENISHMENT_INVALID,
                  "lot_code and manufacturer_expires_at are required")
    try:
        mfg = parse_dt(mfg_raw, "manufacturer_expires_at")
    except ApiError:
        raise_err(ERR_REPLENISHMENT_INVALID,
                  "manufacturer_expires_at is not a valid timestamp")

    device_model_id = None
    if order.get("emergency_event_id"):
        ev = db.emergency_events.get(order["emergency_event_id"])
        if ev is not None:
            device = db.devices.get(ev["device_id"])
            if device is not None:
                device_model_id = device["device_model_id"]

    lot = new_entity()
    lot.update({
        "campus_id": order["campus_id"],
        "device_model_id": device_model_id,
        "kind": order["kind"],
        "lot_code": lot_code,
        "manufacturer_expires_at": fmt_dt(mfg),
        "quantity_received": order["quantity"],
        "quantity_available": order["quantity"],
    })
    db.consumable_lots[lot["id"]] = lot

    order["status"] = "RECEIVED"
    order["received_lot_id"] = lot["id"]
    touch(order)
    return success(order)


@app.post("/api/replenishment-orders/<orderId>/cancel")
@require_roles("ProgramManager")
def cancel_order(orderId):
    order = get_order_or_404(orderId)
    if order["status"] != "PENDING":
        invalid_state("Order is not PENDING")
    order["status"] = "CANCELLED"
    touch(order)
    return success(order)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
