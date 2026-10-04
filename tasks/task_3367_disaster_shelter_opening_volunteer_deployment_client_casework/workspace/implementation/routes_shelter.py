"""Shelter operation lifecycle, dormitory registration, feeding and health."""

from datetime import timedelta

import calc
import core
from core import (apply, authenticate, base_row, clock, find, insert,
                  list_response, must_get, ok_object, parse_instant, read_json,
                  rows, serialize, touch, validate_body)
from errors import ApiError
from flask import Blueprint, request

bp = Blueprint("shelter", __name__)

SHELTER_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager"]
SHELTER_READ_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager",
                      "Caseworker", "Volunteer"]
COORDINATOR_ROLES = ["NationalHQAdmin", "RegionalCoordinator"]


@bp.post("/api/v1/shelter-operations")
def create_shelter_operation():
    authenticate(COORDINATOR_ROLES)
    body = read_json()
    validate_body(body, required={
        "shelter_site_id": str,
        "disaster_relief_operation_id": str,
    })
    site = must_get("shelter_sites", body["shelter_site_id"])
    operation = must_get("disaster_relief_operations", body["disaster_relief_operation_id"])
    if site["region_id"] != operation["region_id"]:
        raise ApiError("ERR_REGION_MISMATCH", 409,
                       "the shelter site is not in the operation's region")
    record = base_row()
    record.update({
        "shelter_site_id": site["id"],
        "disaster_relief_operation_id": operation["id"],
        "opened_at": None,
        "posture": "PENDING_OPEN",
        "occupied_beds": 0,
        "registered_client_count": 0,
        "reunification_pending_count": 0,
        "staffed_volunteer_count": 0,
        "staffing_sufficiency": 0.0,
        "meals_served_total": 0,
        "feeding_cost_cents": 0,
        "health_service_count": 0,
        "operational_cost_cents": 0,
    })
    insert("shelter_operations", record)
    calc.refresh_operation(operation)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/shelter-operations/<shelter_id>/open")
def open_shelter(shelter_id):
    authenticate(COORDINATOR_ROLES)
    validate_body(read_json(), required={})
    shelter = must_get("shelter_operations", shelter_id)
    if shelter["posture"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the shelter is closed")
    if shelter["posture"] != "PENDING_OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "the shelter is not pending open")
    site = must_get("shelter_sites", shelter["shelter_site_id"])
    if site["agreement_status"] != "APPROVED":
        raise ApiError("ERR_SITE_NOT_APPROVED", 409, "the shelter site agreement is not approved")
    if site["inspection_result"] not in ("PASS", "CONDITIONAL_PASS"):
        raise ApiError("ERR_INVALID_STATE", 409, "the shelter site has no passing inspection")
    if site.get("last_inspection_at"):
        age = clock.now - parse_instant(site["last_inspection_at"])
        if age > timedelta(days=calc.INSPECTION_VALIDITY_DAYS):
            raise ApiError("ERR_INSPECTION_STALE", 409, "the latest inspection is stale")
    operation = must_get("disaster_relief_operations", shelter["disaster_relief_operation_id"])
    if operation["phase"] not in ("MOBILIZATION", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "the operation does not admit opening a shelter")
    calc.refresh_shelter(shelter)
    if shelter["staffing_sufficiency"] < calc.RESTRICTED_THRESHOLD:
        raise ApiError("ERR_INVALID_STATE", 409, "the shelter is not sufficiently staffed")
    shelter["posture"] = "OPEN"
    shelter["opened_at"] = core.now_iso()
    touch(shelter)
    calc.refresh_operation(operation)
    return ok_object(serialize(shelter))


@bp.post("/api/v1/shelter-operations/<shelter_id>/close")
def close_shelter(shelter_id):
    authenticate(COORDINATOR_ROLES)
    validate_body(read_json(), required={})
    shelter = must_get("shelter_operations", shelter_id)
    posture = shelter["posture"]
    if posture == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the shelter is closed")
    calc.refresh_shelter(shelter)
    if posture in ("OPEN", "RESTRICTED"):
        operation = must_get("disaster_relief_operations", shelter["disaster_relief_operation_id"])
        if operation["phase"] != "DEMOBILIZATION":
            raise ApiError("ERR_INVALID_STATE", 409, "the operation is not demobilizing")
        # PRD 2.4: closing with clients still inside consolidates; closing with
        # registered_client_count of zero moves the shelter straight to CLOSED,
        # which is the only way an empty shelter can ever reach its terminal
        # value.
        if shelter["registered_client_count"] > 0:
            shelter["posture"] = "CONSOLIDATING"
            touch(shelter)
        else:
            shelter["posture"] = "CLOSED"
            touch(shelter)
            _cascade_close(shelter)
    elif posture == "CONSOLIDATING":
        if shelter["registered_client_count"] != 0:
            raise ApiError("ERR_INVALID_STATE", 409, "clients remain registered at the shelter")
        shelter["posture"] = "CLOSED"
        touch(shelter)
        _cascade_close(shelter)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "the shelter cannot be closed from this posture")
    operation = must_get("disaster_relief_operations", shelter["disaster_relief_operation_id"])
    calc.refresh_operation(operation)
    return ok_object(serialize(shelter))


def _cascade_close(shelter):
    for deployment in rows("volunteer_deployments"):
        if deployment.get("shelter_operation_id") != shelter["id"]:
            continue
        if deployment["status"] not in ("ARRIVED", "ON_SHIFT"):
            continue
        deployment["status"] = "RECALLED"
        touch(deployment)
        volunteer = find("volunteers", deployment["volunteer_id"])
        if volunteer is not None:
            volunteer["deployment_availability"] = "AVAILABLE"
            touch(volunteer)
            region = find("regions", volunteer["home_region_id"])
            if region is not None:
                calc.refresh_region(region)
        for shift in rows("shift_assignments"):
            if shift["volunteer_deployment_id"] == deployment["id"] and shift["status"] in ("SCHEDULED", "CHECKED_IN"):
                shift["status"] = "CANCELLED"
                touch(shift)
    calc.refresh_shelter(shelter)


@bp.get("/api/v1/shelter-operations/<shelter_id>")
def read_shelter_operation(shelter_id):
    authenticate(SHELTER_READ_ROLES)
    shelter = must_get("shelter_operations", shelter_id)
    calc.refresh_shelter_and_posture(shelter)
    apply(shelter, {"operational_cost_cents": calc.operational_cost(shelter, "PROVISIONAL")})
    mode = request.args.get("reporting_mode") or "PROVISIONAL"
    payload = serialize(shelter)
    payload["operational_cost_cents"] = calc.operational_cost(
        shelter, "FINAL" if mode == "FINAL" else "PROVISIONAL")
    return ok_object(payload)


@bp.get("/api/v1/shelter-operations")
def list_shelter_operations():
    authenticate(SHELTER_ROLES)
    shelters = rows("shelter_operations")
    site_id = request.args.get("shelter_site_id")
    operation_id = request.args.get("disaster_relief_operation_id")
    if site_id:
        shelters = [s for s in shelters if s["shelter_site_id"] == site_id]
    if operation_id:
        shelters = [s for s in shelters if s["disaster_relief_operation_id"] == operation_id]
    return list_response(shelters)


# ------------------------------------------------------------- registration


def _bed_conflict(registrations, requested_code, from_dt):
    buffer_start = from_dt - timedelta(minutes=calc.BED_TURNOVER_BUFFER_MINUTES)
    for registration in registrations:
        if registration.get("dormitory_bed_code") != requested_code:
            continue
        until = registration.get("occupied_until_at")
        if registration["status"] == "REGISTERED" and (
                until is None or parse_instant(until) > from_dt):
            return True
        if until is not None:
            until_dt = parse_instant(until)
            if buffer_start < until_dt <= from_dt:
                return True
    return False


def _select_bed(shelter, site, from_dt):
    capacity = int(site["capacity_verified_beds"])
    registrations = calc.shelter_registrations(shelter["id"])
    buffer_start = from_dt - timedelta(minutes=calc.BED_TURNOVER_BUFFER_MINUTES)
    blocked = set()
    for registration in registrations:
        code = registration.get("dormitory_bed_code")
        if not code:
            continue
        until = registration.get("occupied_until_at")
        if registration["status"] == "REGISTERED" and (
                until is None or parse_instant(until) > from_dt):
            blocked.add(code)
        if until is not None:
            until_dt = parse_instant(until)
            if buffer_start < until_dt <= from_dt:
                blocked.add(code)
    counts = {}
    for registration in registrations:
        code = registration.get("dormitory_bed_code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    eligible = ["B-%03d" % n for n in range(1, capacity + 1) if "B-%03d" % n not in blocked]
    if not eligible:
        raise ApiError("ERR_NO_BED_AVAILABLE", 409, "no dormitory bed is available")
    eligible.sort(key=lambda code: (counts.get(code, 0), code))
    return eligible[0]


@bp.post("/api/v1/shelter-operations/<shelter_id>/registrations")
def create_registration(shelter_id):
    authenticate(SHELTER_ROLES)
    body = read_json()
    validate_body(body, required={
        "client_id": str,
        "occupied_from_at": "instant",
        "functional_needs_flag": bool,
    }, optional={
        "requested_bed_code": str,
        "occupied_until_at": "instant",
        "reunification_reference": str,
    })
    shelter = must_get("shelter_operations", shelter_id)
    client = must_get("clients", body["client_id"])
    site = must_get("shelter_sites", shelter["shelter_site_id"])
    if shelter["posture"] == "RESTRICTED":
        raise ApiError("ERR_SHELTER_RESTRICTED", 409,
                       "the shelter is restricted and is not accepting registrations")
    if shelter["posture"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "the shelter is not accepting registrations")
    if body["functional_needs_flag"] and not site["functional_needs_support"]:
        raise ApiError("ERR_FUNCTIONAL_NEEDS_UNSUPPORTED", 409,
                       "the site does not support functional needs")
    from_dt = parse_instant(body["occupied_from_at"])
    registrations = calc.shelter_registrations(shelter["id"])
    requested = body.get("requested_bed_code")
    if requested is not None and _bed_conflict(registrations, requested, from_dt):
        raise ApiError("ERR_BED_OCCUPANCY_CONFLICT", 409, "the requested bed is not free")
    calc.refresh_shelter(shelter)
    if shelter["occupied_beds"] + 1 > int(site["capacity_verified_beds"]):
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "the shelter is at capacity")
    bed_code = requested if requested is not None else _select_bed(shelter, site, from_dt)
    record = base_row()
    record.update({
        "shelter_operation_id": shelter["id"],
        "client_id": client["id"],
        "requested_bed_code": requested,
        "dormitory_bed_code": bed_code,
        "occupied_from_at": core.iso_of(body["occupied_from_at"]),
        "occupied_until_at": core.iso_of(body["occupied_until_at"]) if body.get("occupied_until_at") else None,
        "functional_needs_flag": body["functional_needs_flag"],
        "reunification_reference": body.get("reunification_reference"),
        "reunification_status": "PENDING" if body.get("reunification_reference") else "NOT_REQUESTED",
        "reunification_verified_by_user_id": None,
        "health_service_count": 0,
        "status": "REGISTERED",
    })
    insert("shelter_registrations", record)
    calc.refresh_shelter_and_posture(shelter)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/shelter-registrations/<registration_id>/check-out")
def check_out(registration_id):
    authenticate(SHELTER_ROLES)
    body = read_json()
    validate_body(body, optional={"reunification_verified_by_user_id": str})
    user_id, _role = authenticate(SHELTER_ROLES)
    registration = must_get("shelter_registrations", registration_id)
    if registration["status"] != "REGISTERED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the registration is already closed")
    verifier = body.get("reunification_verified_by_user_id")
    recorded = registration.get("reunification_verified_by_user_id")
    if recorded and recorded == user_id:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "the verifying operator may not release the client")
    if verifier is not None:
        if verifier == user_id:
            raise ApiError("ERR_SOD_VIOLATION", 403,
                           "the verifying operator may not release the client")
        registration["reunification_verified_by_user_id"] = verifier
        registration["reunification_status"] = "VERIFIED"
    if registration["reunification_status"] == "VERIFIED":
        registration["status"] = "REUNIFIED"
        registration["reunification_status"] = "REUNIFIED"
    else:
        registration["status"] = "CHECKED_OUT"
    registration["occupied_until_at"] = core.now_iso()
    touch(registration)
    shelter = find("shelter_operations", registration["shelter_operation_id"])
    if shelter is not None:
        calc.refresh_shelter_and_posture(shelter)
    return ok_object(serialize(registration))


# --------------------------------------------------------- shelter services


@bp.post("/api/v1/shelter-operations/<shelter_id>/feeding-services")
def record_feeding(shelter_id):
    authenticate(SHELTER_ROLES)
    body = read_json()
    validate_body(body, required={
        "meal_type": str,
        "served_at": "instant",
        "meals_planned": int,
        "meals_served": int,
        "unit_cost_cents": int,
    })
    shelter = must_get("shelter_operations", shelter_id)
    for field in ("meals_planned", "meals_served", "unit_cost_cents"):
        if body[field] < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be >= 0" % field)
    line_cents = calc.feeding_line_cost(body["meals_served"], body["unit_cost_cents"])
    core.feeding_events.setdefault(shelter["id"], []).append({
        "meal_type": body["meal_type"],
        "served_at": core.iso_of(body["served_at"]),
        "meals_planned": body["meals_planned"],
        "meals_served": body["meals_served"],
        "unit_cost_cents": body["unit_cost_cents"],
        "line_cents": line_cents,
    })
    shelter["feeding_cost_cents"] = int(shelter["feeding_cost_cents"]) + line_cents
    shelter["meals_served_total"] = int(shelter["meals_served_total"]) + int(body["meals_served"])
    touch(shelter)
    return ok_object(serialize(shelter), 201)


@bp.post("/api/v1/shelter-operations/<shelter_id>/health-services")
def record_health_service(shelter_id):
    authenticate(SHELTER_ROLES)
    body = read_json()
    validate_body(body, required={
        "client_id": str,
        "encounter_type": str,
        "occurred_at": "instant",
    })
    shelter = must_get("shelter_operations", shelter_id)
    client = must_get("clients", body["client_id"])
    shelter["health_service_count"] = int(shelter["health_service_count"]) + 1
    touch(shelter)
    candidates = [r for r in calc.shelter_registrations(shelter["id"])
                  if r["client_id"] == client["id"]]
    if candidates:
        candidates.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
        registration = candidates[-1]
        registration["health_service_count"] = int(registration["health_service_count"]) + 1
        touch(registration)
    return ok_object(serialize(shelter), 201)
