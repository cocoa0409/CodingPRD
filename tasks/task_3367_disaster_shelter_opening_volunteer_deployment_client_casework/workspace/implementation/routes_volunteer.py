"""Volunteers, deployments, rotations and shift assignments."""

from datetime import timedelta

import calc
import core
from core import (authenticate, base_row, clock, find, insert, list_response,
                  must_get, ok_object, parse_instant, read_json, rows, serialize,
                  touch, validate_body, validate_enum)
from errors import ApiError
from flask import Blueprint, request

bp = Blueprint("volunteer", __name__)

COORDINATOR_ROLES = ["NationalHQAdmin", "RegionalCoordinator"]
DEPLOYMENT_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager", "Volunteer"]
SHIFT_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager"]
ROLE_CODES = ("SHELTER_MANAGER", "REGISTRATION", "DORMITORY", "FEEDING",
              "HEALTH_SERVICES", "REUNIFICATION", "CASEWORK")
TRAVEL_MODES = ("AIR", "GROUND", "SELF")
FUNCTIONAL_AREAS = ("REGISTRATION", "DORMITORY", "FEEDING", "HEALTH",
                    "REUNIFICATION", "SECURITY")
NON_TERMINAL_SHIFT = ("SCHEDULED", "CHECKED_IN")


def _refresh_home_region(volunteer):
    region = find("regions", volunteer["home_region_id"])
    if region is not None:
        calc.refresh_region(region)


def _refresh_shelter_of(deployment):
    shelter_id = deployment.get("shelter_operation_id")
    if not shelter_id:
        return
    shelter = find("shelter_operations", shelter_id)
    if shelter is not None:
        calc.refresh_shelter_and_posture(shelter)


# ---------------------------------------------------------------- volunteers


@bp.post("/api/v1/volunteers")
def create_volunteer():
    authenticate(COORDINATOR_ROLES)
    body = read_json()
    validate_body(body, required={
        "full_name": str,
        "home_region_id": str,
        "qualified_role_codes": list,
    })
    must_get("regions", body["home_region_id"])
    record = base_row()
    record.update({
        "full_name": body["full_name"],
        "home_region_id": body["home_region_id"],
        "qualified_role_codes": body["qualified_role_codes"],
        "credential_status": "PENDING",
        "credential_refreshed_at": None,
        "credential_expires_at": None,
        "deployment_availability": "UNAVAILABLE",
        "rotation_days_used_ytd": 0,
    })
    insert("volunteers", record)
    _refresh_home_region(record)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/volunteers/<volunteer_id>/credential-refresh")
def credential_refresh(volunteer_id):
    authenticate(COORDINATOR_ROLES)
    validate_body(read_json(), required={})
    volunteer = must_get("volunteers", volunteer_id)
    volunteer["credential_refreshed_at"] = core.now_iso()
    volunteer["credential_expires_at"] = core.plus_days_iso(calc.CREDENTIAL_VALIDITY_DAYS)
    volunteer["credential_status"] = "ACTIVE"
    volunteer["deployment_availability"] = "AVAILABLE"
    touch(volunteer)
    _refresh_home_region(volunteer)
    return ok_object(serialize(volunteer))


@bp.get("/api/v1/volunteers/<volunteer_id>")
def read_volunteer(volunteer_id):
    authenticate(["NationalHQAdmin", "RegionalCoordinator", "Volunteer"])
    return ok_object(serialize(must_get("volunteers", volunteer_id)))


# --------------------------------------------------------------- deployments


@bp.post("/api/v1/volunteer-deployments")
def create_deployment():
    authenticate(COORDINATOR_ROLES)
    body = read_json()
    validate_body(body, required={
        "volunteer_id": str,
        "disaster_relief_operation_id": str,
        "role_code": str,
        "travel_mode": str,
        "rotation_start_at": "instant",
        "rotation_days": int,
    }, optional={"shelter_operation_id": str})
    validate_enum("role_code", body["role_code"], ROLE_CODES)
    validate_enum("travel_mode", body["travel_mode"], TRAVEL_MODES)
    volunteer = must_get("volunteers", body["volunteer_id"])
    operation = must_get("disaster_relief_operations", body["disaster_relief_operation_id"])
    shelter = None
    if body.get("shelter_operation_id"):
        shelter = must_get("shelter_operations", body["shelter_operation_id"])
    if (volunteer["credential_status"] != "ACTIVE"
            or volunteer["deployment_availability"] != "AVAILABLE"
            or body["role_code"] not in (volunteer.get("qualified_role_codes") or [])):
        raise ApiError("ERR_VOLUNTEER_NOT_CREDENTIALED", 409,
                       "the volunteer is not credentialed for this deployment")
    if body["rotation_days"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "rotation_days must be >= 1")
    if body["rotation_days"] > 21:
        raise ApiError("ERR_ROTATION_TOO_LONG", 422, "rotation_days must be <= 21")
    if shelter is not None and shelter["disaster_relief_operation_id"] != operation["id"]:
        raise ApiError("ERR_DEPLOYMENT_SHELTER_MISMATCH", 409,
                       "the shelter belongs to a different operation")
    record = base_row()
    record.update({
        "volunteer_id": volunteer["id"],
        "disaster_relief_operation_id": operation["id"],
        "shelter_operation_id": shelter["id"] if shelter else None,
        "role_code": body["role_code"],
        "travel_mode": body["travel_mode"],
        "rotation_start_at": core.iso_of(body["rotation_start_at"]),
        "rotation_days": body["rotation_days"],
        "travel_cost_cents": 0,
        "status": "REQUESTED",
    })
    insert("volunteer_deployments", record)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/volunteer-deployments/<deployment_id>/approve")
def approve_deployment(deployment_id):
    authenticate(COORDINATOR_ROLES)
    validate_body(read_json(), required={})
    deployment = must_get("volunteer_deployments", deployment_id)
    if deployment["status"] in calc.TERMINAL_DEPLOYMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the deployment is terminal")
    if deployment["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "the deployment is not requested")
    volunteer = must_get("volunteers", deployment["volunteer_id"])
    operation = must_get("disaster_relief_operations", deployment["disaster_relief_operation_id"])
    if (volunteer["credential_status"] != "ACTIVE"
            or volunteer["deployment_availability"] != "AVAILABLE"
            or deployment["role_code"] not in (volunteer.get("qualified_role_codes") or [])):
        raise ApiError("ERR_VOLUNTEER_NOT_CREDENTIALED", 409,
                       "the volunteer is not credentialed for this deployment")
    if deployment["rotation_days"] > 21:
        raise ApiError("ERR_ROTATION_TOO_LONG", 422, "rotation_days must be <= 21")
    if int(volunteer["rotation_days_used_ytd"]) + int(deployment["rotation_days"]) > 40:
        raise ApiError("ERR_ANNUAL_ROTATION_CAP", 422, "the annual rotation cap is exceeded")
    if deployment.get("shelter_operation_id"):
        shelter = must_get("shelter_operations", deployment["shelter_operation_id"])
        if shelter["disaster_relief_operation_id"] != operation["id"]:
            raise ApiError("ERR_DEPLOYMENT_SHELTER_MISMATCH", 409,
                           "the shelter belongs to a different operation")
    deployment["travel_cost_cents"] = calc.travel_cost(
        volunteer, operation, deployment["travel_mode"], deployment["rotation_days"])
    deployment["status"] = "APPROVED"
    touch(deployment)
    volunteer["deployment_availability"] = "DEPLOYED"
    touch(volunteer)
    _refresh_home_region(volunteer)
    return ok_object(serialize(deployment))


@bp.post("/api/v1/volunteer-deployments/<deployment_id>/end-rotation")
def end_rotation(deployment_id):
    user_id, _role = authenticate(["Volunteer"])
    validate_body(read_json(), required={})
    deployment = must_get("volunteer_deployments", deployment_id)
    if deployment["status"] in calc.TERMINAL_DEPLOYMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the deployment is terminal")
    if user_id != deployment["volunteer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "the volunteer does not own this deployment")
    if deployment["status"] != "ON_SHIFT":
        raise ApiError("ERR_INVALID_STATE", 409, "the deployment is not on shift")
    deployment["status"] = "ROTATION_ENDED"
    touch(deployment)
    volunteer = must_get("volunteers", deployment["volunteer_id"])
    volunteer["deployment_availability"] = "RESTING"
    volunteer["rotation_days_used_ytd"] = (int(volunteer["rotation_days_used_ytd"])
                                           + int(deployment["rotation_days"]))
    touch(volunteer)
    _refresh_home_region(volunteer)
    _refresh_shelter_of(deployment)
    return ok_object(serialize(deployment))


@bp.post("/api/v1/volunteer-deployments/<deployment_id>/recall")
def recall_deployment(deployment_id):
    authenticate(COORDINATOR_ROLES)
    validate_body(read_json(), required={})
    deployment = must_get("volunteer_deployments", deployment_id)
    if deployment["status"] in calc.TERMINAL_DEPLOYMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the deployment is terminal")
    if deployment["status"] == "REQUESTED":
        deployment["status"] = "CANCELLED"
    else:
        deployment["status"] = "RECALLED"
        volunteer = must_get("volunteers", deployment["volunteer_id"])
        volunteer["deployment_availability"] = "AVAILABLE"
        touch(volunteer)
        _refresh_home_region(volunteer)
    touch(deployment)
    for shift in rows("shift_assignments"):
        if shift["volunteer_deployment_id"] == deployment["id"] and shift["status"] in NON_TERMINAL_SHIFT:
            shift["status"] = "CANCELLED"
            touch(shift)
    _refresh_shelter_of(deployment)
    return ok_object(serialize(deployment))


@bp.get("/api/v1/volunteer-deployments/<deployment_id>")
def read_deployment(deployment_id):
    authenticate(DEPLOYMENT_ROLES)
    return ok_object(serialize(must_get("volunteer_deployments", deployment_id)))


@bp.get("/api/v1/volunteer-deployments")
def list_deployments():
    authenticate(["NationalHQAdmin", "RegionalCoordinator", "ShelterManager"])
    deployments = rows("volunteer_deployments")
    volunteer_id = request.args.get("volunteer_id")
    operation_id = request.args.get("disaster_relief_operation_id")
    shelter_id = request.args.get("shelter_operation_id")
    if volunteer_id:
        deployments = [d for d in deployments if d["volunteer_id"] == volunteer_id]
    if operation_id:
        deployments = [d for d in deployments if d["disaster_relief_operation_id"] == operation_id]
    if shelter_id:
        deployments = [d for d in deployments if d.get("shelter_operation_id") == shelter_id]
    return list_response(deployments)


# -------------------------------------------------------------------- shifts


@bp.post("/api/v1/shift-assignments")
def create_shift():
    authenticate(SHIFT_ROLES)
    body = read_json()
    validate_body(body, required={
        "volunteer_deployment_id": str,
        "shelter_operation_id": str,
        "functional_area": str,
        "shift_start_at": "instant",
        "shift_end_at": "instant",
    })
    validate_enum("functional_area", body["functional_area"], FUNCTIONAL_AREAS)
    deployment = must_get("volunteer_deployments", body["volunteer_deployment_id"])
    shelter = must_get("shelter_operations", body["shelter_operation_id"])
    start = parse_instant(body["shift_start_at"])
    end = parse_instant(body["shift_end_at"])
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "shift_end_at must be strictly after shift_start_at")
    if deployment["status"] in calc.TERMINAL_DEPLOYMENT:
        raise ApiError("ERR_INVALID_STATE", 409, "the deployment is terminal")
    volunteer_id = deployment["volunteer_id"]
    for shift in rows("shift_assignments"):
        if shift["status"] == "CANCELLED":
            continue
        other = find("volunteer_deployments", shift["volunteer_deployment_id"])
        if other is None or other["volunteer_id"] != volunteer_id:
            continue
        other_start = parse_instant(shift["shift_start_at"])
        other_end = parse_instant(shift["shift_end_at"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_SHIFT_OVERLAP", 409,
                           "the volunteer already holds an overlapping shift")
    open_shifts = sum(1 for shift in rows("shift_assignments")
                      if shift["volunteer_deployment_id"] == deployment["id"]
                      and shift["status"] in NON_TERMINAL_SHIFT)
    if open_shifts >= 3:
        raise ApiError("ERR_MAX_SHIFTS_EXCEEDED", 409,
                       "the deployment already holds three non-terminal shifts")
    record = base_row()
    record.update({
        "volunteer_deployment_id": deployment["id"],
        "shelter_operation_id": shelter["id"],
        "functional_area": body["functional_area"],
        "shift_start_at": core.iso_of(body["shift_start_at"]),
        "shift_end_at": core.iso_of(body["shift_end_at"]),
        "status": "SCHEDULED",
    })
    insert("shift_assignments", record)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/shift-assignments/<shift_id>/check-in")
def check_in(shift_id):
    user_id, _role = authenticate(["Volunteer"])
    validate_body(read_json(), required={})
    shift = must_get("shift_assignments", shift_id)
    deployment = must_get("volunteer_deployments", shift["volunteer_deployment_id"])
    if user_id != deployment["volunteer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "the volunteer does not own this shift")
    if shift["status"] in ("COMPLETED", "NO_SHOW", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the shift is terminal")
    if shift["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "the shift is not scheduled")
    shelter = must_get("shelter_operations", shift["shelter_operation_id"])
    if shelter["posture"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "the shelter does not admit check-in")
    earliest = parse_instant(shift["shift_start_at"]) - timedelta(minutes=calc.CHECKIN_LEAD_MINUTES)
    if clock.now < earliest:
        raise ApiError("ERR_INVALID_STATE", 409, "check-in is not open yet")
    shift["status"] = "CHECKED_IN"
    touch(shift)
    if deployment["status"] == "ARRIVED":
        deployment["status"] = "ON_SHIFT"
        touch(deployment)
        calc.refresh_shelter_and_posture(shelter)
    return ok_object(serialize(shift))


@bp.get("/api/v1/shift-assignments/<shift_id>")
def read_shift(shift_id):
    authenticate(DEPLOYMENT_ROLES)
    return ok_object(serialize(must_get("shift_assignments", shift_id)))


@bp.get("/api/v1/shift-assignments")
def list_shifts():
    authenticate(["NationalHQAdmin", "RegionalCoordinator", "ShelterManager"])
    shifts = rows("shift_assignments")
    deployment_id = request.args.get("volunteer_deployment_id")
    shelter_id = request.args.get("shelter_operation_id")
    if deployment_id:
        shifts = [s for s in shifts if s["volunteer_deployment_id"] == deployment_id]
    if shelter_id:
        shifts = [s for s in shifts if s["shelter_operation_id"] == shelter_id]
    return list_response(shifts)
