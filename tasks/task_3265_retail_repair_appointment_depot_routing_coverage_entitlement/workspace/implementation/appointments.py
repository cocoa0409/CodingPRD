"""Appointments: booking, check-in, diagnosis, cancellation."""
from datetime import timedelta

from flask import Blueprint, request

from core import (ApiError, BUFFER_MINUTES, ISSUE_CATEGORIES, STORE, auth, body,
                  entity_bootstrap, get_appointment, get_customer, get_device,
                  get_location, logical_now, ok_obj, paginate, pagination, parse_iso,
                  require, require_enum, ser_appointment, touch)

bp = Blueprint("appointments", __name__)

ACTIVE_APPT_STATES = {"SCHEDULED", "CHECKED_IN", "IN_DIAGNOSIS"}


def _slot_conflict(technician_id, start, end, exclude_id=None):
    eff_start = start - timedelta(minutes=BUFFER_MINUTES)
    eff_end = end + timedelta(minutes=BUFFER_MINUTES)
    for a in STORE["appointments"].values():
        if a["technician_id"] != technician_id:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["appointment_status"] not in ACTIVE_APPT_STATES:
            continue
        ex_start = parse_iso(a["slot_start"])
        ex_end = parse_iso(a["slot_end"])
        if eff_start < ex_end and eff_end > ex_start:
            return True
    return False


@bp.post("/appointments")
def create_appointment():
    auth({"Customer", "CustomerService"})
    data = require(body(), "customer_id", "device_id", "location_id", "technician_id",
                   "slot_start", "slot_end", "issue_category")
    require_enum(data, "issue_category", ISSUE_CATEGORIES)
    customer = get_customer(data["customer_id"])
    device = get_device(data["device_id"])
    location = get_location(data["location_id"])
    technician = STORE["technicians"].get(data["technician_id"])
    if technician is None:
        raise ApiError("ERR_NOT_FOUND", "Technician not found", 404)
    # business: account not locked/closed (priority 6)
    if customer["account_status"] in ("LOCKED", "CLOSED"):
        raise ApiError("ERR_ACCOUNT_LOCKED", "Customer account is locked or closed", 403)
    slot_start = parse_iso(data["slot_start"])
    slot_end = parse_iso(data["slot_end"])
    # slot conflict (priority 7)
    if _slot_conflict(technician["id"], slot_start, slot_end):
        raise ApiError("ERR_SLOT_CONFLICT",
                       "Requested slot conflicts with an existing appointment", 409)
    # location availability (priority 8)
    if location["location_status"] != "ACTIVE":
        raise ApiError("ERR_LOCATION_UNAVAILABLE", "Service location is not ACTIVE", 422)
    # referential integrity (priority 9)
    if device["customer_id"] != customer["id"]:
        raise ApiError("ERR_INVALID_REFERENCE", "Device does not belong to customer", 422)
    # slot time validity (priority 11)
    now = logical_now()
    if slot_start <= now or slot_start > now + timedelta(days=30):
        raise ApiError("ERR_INVALID_SLOT_TIME",
                       "Appointment slot must be in the future and within 30 days", 422)
    if slot_end <= slot_start:
        raise ApiError("ERR_INVALID_SLOT_TIME", "slot_end must be after slot_start", 422)
    # OCC (priority 14)
    expected = data.get("expected_device_version")
    if expected is not None and expected != device["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_device_version does not match", 412)
    e = entity_bootstrap()
    e.update({
        "customer_id": customer["id"],
        "device_id": device["id"],
        "location_id": location["id"],
        "technician_id": technician["id"],
        "slot_start": data["slot_start"],
        "slot_end": data["slot_end"],
        "issue_category": data["issue_category"],
        "appointment_status": "SCHEDULED",
    })
    STORE["appointments"][e["id"]] = e
    touch(device)  # booking bumps device version
    return ok_obj(ser_appointment(e), 201)


@bp.get("/appointments/<aid>")
def get_appointment_view(aid):
    auth({"Customer", "Technician", "CustomerService"})
    return ok_obj(ser_appointment(get_appointment(aid)))


@bp.get("/appointments")
def list_appointments():
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["appointments"].values())
    for key in ("customer_id", "device_id", "location_id", "technician_id", "appointment_status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a[key] == v]
    return paginate([ser_appointment(a) for a in items], limit, offset)


@bp.post("/appointments/<aid>/check-in")
def check_in(aid):
    auth({"Customer", "Technician"})
    a = get_appointment(aid)
    if a["appointment_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Appointment is not SCHEDULED", 409)
    now = logical_now()
    start = parse_iso(a["slot_start"])
    end = parse_iso(a["slot_end"])
    if now < start - timedelta(minutes=15) or now > end:
        raise ApiError("ERR_INVALID_STATE",
                       "Check-in window is from 15 minutes before slot_start until slot_end", 409)
    a["appointment_status"] = "CHECKED_IN"
    touch(a)
    return ok_obj(ser_appointment(a))


@bp.post("/appointments/<aid>/start-diagnosis")
def start_diagnosis(aid):
    user_id, role = auth({"Technician"})
    a = get_appointment(aid)
    if a["appointment_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "Appointment is not CHECKED_IN", 409)
    tech = STORE["technicians"].get(user_id)
    if tech is None or tech["location_id"] != a["location_id"] or not tech.get("is_active", False):
        raise ApiError("ERR_UNAUTHORIZED",
                       "Technician must be active at the appointment's location", 403)
    a["appointment_status"] = "IN_DIAGNOSIS"
    touch(a)
    return ok_obj(ser_appointment(a))


@bp.post("/appointments/<aid>/complete-diagnosis")
def complete_diagnosis(aid):
    auth({"Technician"})
    a = get_appointment(aid)
    if a["appointment_status"] != "IN_DIAGNOSIS":
        raise ApiError("ERR_INVALID_STATE", "Appointment is not IN_DIAGNOSIS", 409)
    a["appointment_status"] = "COMPLETED"
    touch(a)
    return ok_obj(ser_appointment(a))


@bp.post("/appointments/<aid>/cancel")
def cancel_appointment(aid):
    user_id, role = auth({"Customer", "Technician", "CustomerService"})
    a = get_appointment(aid)
    if a["appointment_status"] == "SCHEDULED":
        pass
    elif a["appointment_status"] == "CHECKED_IN":
        if role != "CustomerService":
            raise ApiError("ERR_UNAUTHORIZED",
                           "Only CustomerService may cancel a checked-in appointment", 403)
    else:
        raise ApiError("ERR_INVALID_STATE", "Appointment cannot be cancelled from its current state", 409)
    a["appointment_status"] = "CANCELLED"
    touch(a)
    return ok_obj(ser_appointment(a))
