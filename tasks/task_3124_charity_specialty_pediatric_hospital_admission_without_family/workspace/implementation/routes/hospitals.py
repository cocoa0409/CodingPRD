"""SpecialtyHospital endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_HOSPITAL_NOT_FOUND, ERR_HOSPITAL_HAS_OPEN_APPLICATIONS)
from helpers import get_body, new_id, iso_date, req_int, req_num, req_str, touch
from middleware import require_auth
from response import success_list, success_object, paginate
from views import hospital_view

bp = Blueprint("hospitals", __name__)

ALL_ROLES = ["NetworkAdmin", "IntakeCoordinator", "ReviewCommitteeMember",
             "BillingSpecialist", "CareCoordinator", "OutreachPlanner",
             "PhilanthropyOfficer", "ReferringPhysician"]


def get_hospital_or_404(hospital_id):
    h = db.hospitals.get(hospital_id)
    if h is None:
        raise ApiError(ERR_HOSPITAL_NOT_FOUND, 404, "Hospital id does not exist")
    return h


@bp.post("/hospitals")
def create_hospital():
    require_auth(["NetworkAdmin"])
    body = get_body()
    hospital_code = req_str(body, "hospital_code")
    name = req_str(body, "name")
    city = req_str(body, "city")
    state_code = req_str(body, "state_code")
    latitude = req_num(body, "latitude", minimum=-90.0, maximum=90.0)
    longitude = req_num(body, "longitude", minimum=-180.0, maximum=180.0)
    annual_capacity = req_int(body, "annual_capacity", minimum=1)
    # created_at/updated_at track the logical clock (millisecond precision)
    now = db.CLOCK.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
    h = {
        "id": new_id(),
        "hospital_code": hospital_code,
        "name": name,
        "city": city,
        "state_code": state_code,
        "latitude": latitude,
        "longitude": longitude,
        "annual_capacity": annual_capacity,
        "admissions_ytd": 0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.hospitals[h["id"]] = h
    return success_object(hospital_view(h), 201)


@bp.get("/hospitals")
def list_hospitals():
    require_auth(ALL_ROLES)
    items = list(db.hospitals.values())
    status = request.args.get("status")
    if status:
        items = [h for h in items if h["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([hospital_view(h) for h in page], total, limit, offset)


@bp.get("/hospitals/<hospitalId>")
def get_hospital(hospitalId):
    require_auth(ALL_ROLES)
    h = get_hospital_or_404(hospitalId)
    return success_object(hospital_view(h))


@bp.post("/hospitals/<hospitalId>/suspend")
def suspend_hospital(hospitalId):
    require_auth(["NetworkAdmin"])
    h = get_hospital_or_404(hospitalId)
    if h["status"] != "OPEN":
        from errors import invalid_state
        raise invalid_state("Hospital must be OPEN to suspend")
    h["status"] = "SUSPENDED"
    touch(h)
    # Cascade: ACTIVE programs -> SUSPENDED
    for p in db.programs.values():
        if p["hospital_id"] == h["id"] and p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            touch(p)
    # Cascade: PROPOSED clinics -> CANCELLED_CLINIC; their BOOKED screenings -> EXPIRED
    for c in db.clinics.values():
        if c["hospital_id"] == h["id"] and c["status"] == "PROPOSED":
            c["status"] = "CANCELLED_CLINIC"
            for s in db.screenings.values():
                if s["clinic_id"] == c["id"] and s["status"] == "BOOKED":
                    s["status"] = "EXPIRED"
                    touch(s)
                    c["booked_screening_count"] -= 1
            touch(c)
    return success_object(hospital_view(h))


@bp.post("/hospitals/<hospitalId>/reopen")
def reopen_hospital(hospitalId):
    require_auth(["NetworkAdmin"])
    h = get_hospital_or_404(hospitalId)
    if h["status"] != "SUSPENDED":
        from errors import invalid_state
        raise invalid_state("Hospital must be SUSPENDED to reopen")
    h["status"] = "OPEN"
    touch(h)
    # Programs remain SUSPENDED — no auto-restore (PRD §3.1)
    return success_object(hospital_view(h))


@bp.post("/hospitals/<hospitalId>/close")
def close_hospital(hospitalId):
    require_auth(["NetworkAdmin"])
    h = get_hospital_or_404(hospitalId)
    if h["status"] not in ("OPEN", "SUSPENDED"):
        from errors import invalid_state
        raise invalid_state("Hospital must be OPEN or SUSPENDED to close")
    # No non-terminal application may reference any program of this hospital
    program_ids = {p["id"] for p in db.programs.values() if p["hospital_id"] == h["id"]}
    for app in db.applications.values():
        if app["program_id"] in program_ids and app["status"] in (
                "SUBMITTED", "PENDING_REVIEW", "INFO_REQUESTED"):
            raise ApiError(ERR_HOSPITAL_HAS_OPEN_APPLICATIONS, 409,
                           "Hospital close blocked by non-terminal applications")
    closing_from_open = h["status"] == "OPEN"
    h["status"] = "CLOSED"
    touch(h)
    if closing_from_open:
        for p in db.programs.values():
            if p["hospital_id"] == h["id"] and p["status"] == "ACTIVE":
                p["status"] = "SUSPENDED"
                touch(p)
    return success_object(hospital_view(h))
