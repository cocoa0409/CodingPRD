from flask import Blueprint, request

import db
from errors import (
    err_battery_too_low, err_device_not_docked, err_device_still_assigned,
    err_device_unhealthy, err_invalid_state, err_lead_cases_open, err_not_found,
    err_officer_already_has_device, err_officer_not_active, err_unauthorized,
    err_validation,
)
from helpers import (
    body, get_agency_or_404, get_scoped, iso_now, new_resource, paginate,
    parse_dt, reject_unknown, require_enum, require_int, require_str,
    success_obj, touch, write_audit,
)
from middleware import authenticate, require_roles
import services

bp = Blueprint("roster_fleet", __name__)

RANKS = ["OFFICER", "CORPORAL", "SERGEANT", "LIEUTENANT"]


def officer_has_device(officer_id):
    for d in db.collection("devices").values():
        if (d["assigned_officer_id"] == officer_id
                and d["assignment_status"] == "ASSIGNED"
                and d["health_status"] != "RETIRED"):
            return True
    return False


# ---------------------------------------------------------------- officers

@bp.route("/agencies/<agency_id>/officers", methods=["POST"])
def create_officer(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"badge_number", "full_name", "rank"})
    badge = require_str(data, "badge_number")
    full_name = require_str(data, "full_name")
    rank = require_enum(data, "rank", RANKS)
    for o in db.collection("officers").values():
        if (o["agency_id"] == agency["id"] and o["badge_number"] == badge
                and o["status"] in ("ACTIVE", "SUSPENDED")):
            raise err_validation("badge_number already in use")
    officer = new_resource({
        "agency_id": agency["id"],
        "badge_number": badge,
        "full_name": full_name,
        "rank": rank,
        "status": "ACTIVE",
        "recordings_uploaded_count": 0,
        "pending_review_count": 0,
    })
    db.collection("officers")[officer["id"]] = officer
    return success_obj(officer, 201)


@bp.route("/agencies/officers", methods=["GET"])
def list_officers():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Supervisor",
                  "RecordsOfficer")
    items = list(db.collection("officers").values())
    agency_id = request.args.get("agency_id")
    if agency_id:
        items = [o for o in items if o["agency_id"] == agency_id]
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    return paginate(items)


@bp.route("/agencies/<agency_id>/officers/<officer_id>", methods=["GET"])
def get_officer(agency_id, officer_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Supervisor",
                  "RecordsOfficer", "Officer")
    agency = get_agency_or_404(agency_id)
    officer = get_scoped("officers", agency, officer_id, "Officer")
    return success_obj(officer)


@bp.route("/agencies/officers/<officer_id>", methods=["GET"])
def get_officer_flat(officer_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Supervisor",
                  "RecordsOfficer", "Officer")
    officer = db.collection("officers").get(officer_id)
    if officer is None:
        raise err_not_found("Officer not found")
    return success_obj(officer)


def _officer_action(agency_id, officer_id, action):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    officer = get_scoped("officers", agency, officer_id, "Officer")
    return actor, agency, officer


@bp.route("/agencies/<agency_id>/officers/<officer_id>/suspend", methods=["POST"])
def suspend_officer(agency_id, officer_id):
    actor, agency, officer = _officer_action(agency_id, officer_id, "suspend")
    if officer["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE officer can be suspended")
    if officer_has_device(officer["id"]):
        raise err_device_still_assigned()
    officer["status"] = "SUSPENDED"
    touch(officer)
    write_audit(agency["id"], actor, "OFFICER_SUSPENDED", "Officer",
                officer["id"], "status ACTIVE -> SUSPENDED")
    return success_obj(officer)


@bp.route("/agencies/<agency_id>/officers/<officer_id>/reinstate", methods=["POST"])
def reinstate_officer(agency_id, officer_id):
    actor, agency, officer = _officer_action(agency_id, officer_id, "reinstate")
    if officer["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED officer can be reinstated")
    officer["status"] = "ACTIVE"
    touch(officer)
    write_audit(agency["id"], actor, "OFFICER_REINSTATED", "Officer",
                officer["id"], "status SUSPENDED -> ACTIVE")
    return success_obj(officer)


@bp.route("/agencies/<agency_id>/officers/<officer_id>/retire", methods=["POST"])
def retire_officer(agency_id, officer_id):
    actor, agency, officer = _officer_action(agency_id, officer_id, "retire")
    if officer["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE officer can be retired")
    if officer_has_device(officer["id"]):
        raise err_device_still_assigned()
    for c in db.collection("cases").values():
        if (c["agency_id"] == agency["id"]
                and c["lead_officer_id"] == officer["id"]
                and c["status"] in ("OPEN", "UNDER_REVIEW")):
            raise err_lead_cases_open()
    officer["status"] = "RETIRED"
    touch(officer)
    write_audit(agency["id"], actor, "OFFICER_RETIRED", "Officer",
                officer["id"], "status -> RETIRED")
    return success_obj(officer)


# ---------------------------------------------------------------- devices

@bp.route("/agencies/<agency_id>/devices", methods=["POST"])
def create_device(agency_id):
    actor = authenticate()
    require_roles(actor, "DeviceCoordinator")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"serial_number", "model", "battery_pct"})
    serial = require_str(data, "serial_number")
    model = require_str(data, "model")
    battery = require_int(data, "battery_pct", required=False)
    if battery is None:
        battery = 100
    if battery < 0 or battery > 100:
        raise err_validation("battery_pct must be 0..100")
    for d in db.collection("devices").values():
        if d["agency_id"] == agency["id"] and d["serial_number"] == serial:
            raise err_validation("serial_number already in use")
    device = new_resource({
        "agency_id": agency["id"],
        "serial_number": serial,
        "model": model,
        "battery_pct": battery,
        "battery_pct_at_dock": None,
        "docked_at": None,
        "assignment_status": "UNASSIGNED",
        "dock_status": "DOCKED",
        "health_status": "HEALTHY",
        "assigned_officer_id": None,
    })
    db.collection("devices")[device["id"]] = device
    return success_obj(device, 201)


@bp.route("/agencies/devices", methods=["GET"])
def list_devices():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Supervisor")
    items = list(db.collection("devices").values())
    agency_id = request.args.get("agency_id")
    if agency_id:
        items = [d for d in items if d["agency_id"] == agency_id]
    aoid = request.args.get("assigned_officer_id")
    if aoid:
        items = [d for d in items if d.get("assigned_officer_id") == aoid]
    astat = request.args.get("assignment_status")
    if astat:
        items = [d for d in items if d["assignment_status"] == astat]
    hstat = request.args.get("health_status")
    if hstat:
        items = [d for d in items if d["health_status"] == hstat]
    return paginate(items)


@bp.route("/agencies/<agency_id>/devices/<device_id>", methods=["GET"])
def get_device(agency_id, device_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Supervisor", "Officer")
    agency = get_agency_or_404(agency_id)
    device = get_scoped("devices", agency, device_id, "Device")
    return success_obj(device)


@bp.route("/agencies/devices/<device_id>", methods=["GET"])
def get_device_flat(device_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Supervisor", "Officer")
    device = db.collection("devices").get(device_id)
    if device is None:
        raise err_not_found("Device not found")
    return success_obj(device)


@bp.route("/agencies/<agency_id>/devices/<device_id>/assign", methods=["POST"])
def assign_device(agency_id, device_id):
    actor = authenticate()
    require_roles(actor, "DeviceCoordinator")
    agency = get_agency_or_404(agency_id)
    device = get_scoped("devices", agency, device_id, "Device")
    data = body()
    reject_unknown(data, {"officer_id"})
    officer_id = require_str(data, "officer_id")
    officer = db.collection("officers").get(officer_id)
    if officer is None or officer["agency_id"] != agency["id"]:
        raise err_not_found("Officer not found")
    if device["assignment_status"] != "UNASSIGNED":
        raise err_invalid_state("Device is already assigned")
    if device["health_status"] != "HEALTHY":
        raise err_device_unhealthy()
    if device["battery_pct"] < 20:
        raise err_battery_too_low()
    if officer["status"] != "ACTIVE":
        raise err_officer_not_active()
    if officer_has_device(officer["id"]):
        raise err_officer_already_has_device()
    if device["dock_status"] != "DOCKED":
        raise err_device_not_docked()
    device["assignment_status"] = "ASSIGNED"
    device["assigned_officer_id"] = officer["id"]
    touch(device)
    write_audit(agency["id"], actor, "DEVICE_ASSIGNED", "Device",
                device["id"], "assigned to officer %s" % officer["id"])
    return success_obj(device)


@bp.route("/agencies/<agency_id>/devices/<device_id>/unassign", methods=["POST"])
def unassign_device(agency_id, device_id):
    actor = authenticate()
    require_roles(actor, "DeviceCoordinator")
    agency = get_agency_or_404(agency_id)
    device = get_scoped("devices", agency, device_id, "Device")
    if device["assignment_status"] != "ASSIGNED":
        raise err_invalid_state("Device is not assigned")
    if device["dock_status"] != "DOCKED":
        raise err_device_not_docked()
    device["assignment_status"] = "UNASSIGNED"
    device["assigned_officer_id"] = None
    touch(device)
    write_audit(agency["id"], actor, "DEVICE_UNASSIGNED", "Device",
                device["id"], "assigned_officer_id cleared")
    return success_obj(device)


def _dock_actor_check(actor, device):
    if actor["role"] == "Officer" and device.get("assigned_officer_id") != actor["user_id"]:
        raise err_unauthorized("Officer may only dock/undock their own assigned device")


@bp.route("/agencies/<agency_id>/devices/<device_id>/dock", methods=["POST"])
def dock_device(agency_id, device_id):
    actor = authenticate()
    require_roles(actor, "DeviceCoordinator", "Officer")
    agency = get_agency_or_404(agency_id)
    device = get_scoped("devices", agency, device_id, "Device")
    _dock_actor_check(actor, device)
    if device["dock_status"] != "UNDOCKED":
        raise err_invalid_state("Device is not UNDOCKED")
    device["battery_pct_at_dock"] = device["battery_pct"]
    device["docked_at"] = iso_now()
    device["dock_status"] = "DOCKED"
    touch(device)
    write_audit(agency["id"], actor, "DEVICE_DOCKED", "Device",
                device["id"], "device docked")
    return success_obj(device)


@bp.route("/agencies/<agency_id>/devices/<device_id>/undock", methods=["POST"])
def undock_device(agency_id, device_id):
    actor = authenticate()
    require_roles(actor, "DeviceCoordinator", "Officer")
    agency = get_agency_or_404(agency_id)
    device = get_scoped("devices", agency, device_id, "Device")
    _dock_actor_check(actor, device)
    if device["dock_status"] != "DOCKED":
        raise err_invalid_state("Device is not DOCKED")
    gain = services.dock_charge_gain(device, parse_dt(iso_now()))
    device["battery_pct_at_dock"] = None
    device["docked_at"] = None
    device["dock_status"] = "UNDOCKED"
    touch(device)
    write_audit(agency["id"], actor, "DEVICE_UNDOCKED", "Device",
                device["id"], "device undocked; charge_gained_pct=%d" % gain)
    out = dict(device)
    out["charge_gained_pct"] = gain
    return success_obj(out)


@bp.route("/agencies/<agency_id>/devices/<device_id>/retire", methods=["POST"])
def retire_device(agency_id, device_id):
    actor = authenticate()
    require_roles(actor, "DeviceCoordinator")
    agency = get_agency_or_404(agency_id)
    device = get_scoped("devices", agency, device_id, "Device")
    if device["health_status"] == "RETIRED":
        raise err_invalid_state("Device already retired")
    if device["dock_status"] != "DOCKED":
        raise err_device_not_docked()
    if device["assignment_status"] == "ASSIGNED":
        device["assignment_status"] = "UNASSIGNED"
        device["assigned_officer_id"] = None
    device["health_status"] = "RETIRED"
    touch(device)
    write_audit(agency["id"], actor, "DEVICE_RETIRED", "Device",
                device["id"], "health_status -> RETIRED")
    return success_obj(device)
