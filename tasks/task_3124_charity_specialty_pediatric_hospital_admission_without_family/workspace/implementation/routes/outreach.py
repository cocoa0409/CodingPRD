"""OutreachClinic and OutreachScreening endpoints (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_CLINIC_CAPACITY_REACHED,
                    ERR_CLINIC_LOCATION_CONFLICT, ERR_CLINIC_NOT_FOUND,
                    ERR_CLINIC_NOT_IN_PROGRESS, ERR_CLINIC_STILL_RUNNING,
                    ERR_HOSPITAL_NOT_OPEN, ERR_SCREENING_DATE_OUTSIDE_CLINIC,
                    ERR_SCREENING_NOT_FOUND, bad_request, invalid_state)
from helpers import (get_body, haversine_miles, iso_date, new_id, now_iso,
                     parse_dt, req_dt, req_enum, req_int, req_num, req_str,
                     touch)
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.hospitals import get_hospital_or_404
from views import clinic_view, screening_view

bp = Blueprint("outreach", __name__)

LIST_ROLES = ["NetworkAdmin", "IntakeCoordinator", "OutreachPlanner", "CareCoordinator"]

SUSPECTED_CONDITIONS = {"ORTHOPEDIC", "BURN", "CLEFT_CRANIOFACIAL",
                        "SPINAL_CORD", "NEUROMUSCULAR", "OTHER"}

LOCATION_RADIUS_MILES = 25.0
BUFFER_DAYS = 7
CONVERSION_WINDOW_DAYS = 90


def get_clinic_or_404(clinic_id):
    c = db.clinics.get(clinic_id)
    if c is None:
        raise ApiError(ERR_CLINIC_NOT_FOUND, 404, "Outreach clinic id does not exist")
    return c


def get_screening_or_404(screening_id):
    s = db.screenings.get(screening_id)
    if s is None:
        raise ApiError(ERR_SCREENING_NOT_FOUND, 404, "Screening id does not exist")
    return s


def _cancel_clinic(clinic):
    clinic["status"] = "CANCELLED_CLINIC"
    for s in db.screenings.values():
        if s["clinic_id"] == clinic["id"] and s["status"] == "BOOKED":
            s["status"] = "EXPIRED"
            touch(s)
            clinic["booked_screening_count"] -= 1
    touch(clinic)


@bp.post("/hospitals/<id>/outreach-clinics")
def create_clinic(id):
    require_auth(["OutreachPlanner"])
    h = get_hospital_or_404(id)
    body = get_body()
    location_name = req_str(body, "location_name")
    latitude = req_num(body, "latitude")
    longitude = req_num(body, "longitude")
    start_date = req_dt(body, "start_date")
    end_date = req_dt(body, "end_date")
    if end_date < start_date:
        raise bad_request("end_date must be >= start_date")
    screening_capacity = req_int(body, "screening_capacity", minimum=1)
    now = now_iso()
    c = {
        "id": new_id(),
        "hospital_id": h["id"],
        "location_name": location_name,
        "latitude": latitude,
        "longitude": longitude,
        "start_date": iso_date(start_date),
        "end_date": iso_date(end_date),
        "screening_capacity": screening_capacity,
        "booked_screening_count": 0,
        "conversion_deadline": iso_date(end_date + timedelta(days=CONVERSION_WINDOW_DAYS)),
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.clinics[c["id"]] = c
    return success_object(clinic_view(c), 201)


@bp.get("/hospitals/<id>/outreach-clinics")
def list_clinics(id):
    require_auth(LIST_ROLES)
    h = get_hospital_or_404(id)
    items = [c for c in db.clinics.values() if c["hospital_id"] == h["id"]]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([clinic_view(c) for c in page], total, limit, offset)


@bp.get("/outreach-clinics/<clinicId>")
def get_clinic(clinicId):
    require_auth(LIST_ROLES)
    c = get_clinic_or_404(clinicId)
    return success_object(clinic_view(c))


@bp.post("/outreach-clinics/<clinicId>/confirm")
def confirm_clinic(clinicId):
    require_auth(["OutreachPlanner"])
    c = get_clinic_or_404(clinicId)
    if c["status"] != "PROPOSED":
        raise invalid_state("Clinic must be PROPOSED to confirm")
    hospital = db.hospitals.get(c["hospital_id"])
    if hospital is None or hospital["status"] != "OPEN":
        raise ApiError(ERR_HOSPITAL_NOT_OPEN, 409,
                       "Hospital must be OPEN to confirm a clinic")
    this_start = parse_dt(c["start_date"])
    this_end = parse_dt(c["end_date"])
    buffer = timedelta(days=BUFFER_DAYS)
    for other in db.clinics.values():
        if other["id"] == c["id"]:
            continue
        if other["status"] not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        dist = haversine_miles(c["latitude"], c["longitude"],
                               other["latitude"], other["longitude"])
        if dist > LOCATION_RADIUS_MILES:
            continue
        other_start = parse_dt(other["start_date"])
        other_end = parse_dt(other["end_date"])
        # Two clinics conflict unless one's padded end falls strictly before
        # the other's start: NOT (other.end+7d < this.start OR this.end+7d < other.start)
        if not (other_end + buffer < this_start or this_end + buffer < other_start):
            raise ApiError(ERR_CLINIC_LOCATION_CONFLICT, 409,
                           "Another clinic within 25.0 miles has a padded-interval "
                           "(end + 7 days) overlap with this clinic")
    c["status"] = "CONFIRMED"
    touch(c)
    return success_object(clinic_view(c))


@bp.post("/outreach-clinics/<clinicId>/complete")
def complete_clinic(clinicId):
    require_auth(["OutreachPlanner"])
    c = get_clinic_or_404(clinicId)
    if c["status"] != "IN_PROGRESS":
        raise invalid_state("Clinic must be IN_PROGRESS to complete")
    if db.CLOCK <= parse_dt(c["end_date"]):
        raise ApiError(ERR_CLINIC_STILL_RUNNING, 409,
                       "complete requires logical clock past end_date")
    c["status"] = "COMPLETED"
    touch(c)
    for s in db.screenings.values():
        if s["clinic_id"] == c["id"] and s["status"] == "BOOKED":
            s["status"] = "NO_SHOW"
            c["booked_screening_count"] -= 1
            touch(s)
    return success_object(clinic_view(c))


@bp.post("/outreach-clinics/<clinicId>/cancel")
def cancel_clinic(clinicId):
    require_auth(["OutreachPlanner"])
    c = get_clinic_or_404(clinicId)
    if c["status"] not in ("PROPOSED", "CONFIRMED"):
        raise invalid_state("Clinic must be PROPOSED or CONFIRMED to cancel")
    _cancel_clinic(c)
    return success_object(clinic_view(c))


@bp.post("/outreach-clinics/<id>/screenings")
def create_screening(id):
    require_auth(["OutreachPlanner"])
    clinic = get_clinic_or_404(id)
    body = get_body()
    patient_full_name = req_str(body, "patient_full_name")
    dob = req_dt(body, "patient_date_of_birth")
    suspected = req_enum(body, "suspected_condition_category", SUSPECTED_CONDITIONS)
    screening_date = req_dt(body, "screening_date")

    if clinic["status"] == "CANCELLED_CLINIC":
        raise invalid_state("Clinic must be PROPOSED, CONFIRMED, or IN_PROGRESS "
                            "to book a screening")
    hospital = db.hospitals.get(clinic["hospital_id"])
    if hospital is None or hospital["status"] != "OPEN":
        raise ApiError(ERR_HOSPITAL_NOT_OPEN, 409,
                       "Hospital must be OPEN to book a screening")
    if not (parse_dt(clinic["start_date"]) <= screening_date <= parse_dt(clinic["end_date"])):
        raise ApiError(ERR_SCREENING_DATE_OUTSIDE_CLINIC, 409,
                       "screening_date outside the clinic's closed [start_date, end_date] interval")
    if clinic["booked_screening_count"] >= clinic["screening_capacity"]:
        raise ApiError(ERR_CLINIC_CAPACITY_REACHED, 409,
                       "booked_screening_count == screening_capacity")

    now = now_iso()
    s = {
        "id": new_id(),
        "clinic_id": clinic["id"],
        "patient_full_name": patient_full_name,
        "patient_date_of_birth": iso_date(dob),
        "suspected_condition_category": suspected,
        "screening_date": iso_date(screening_date),
        "converted_application_id": None,
        "status": "BOOKED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.screenings[s["id"]] = s
    clinic["booked_screening_count"] += 1
    touch(clinic)
    return success_object(screening_view(s), 201)


@bp.get("/outreach-clinics/<id>/screenings")
def list_screenings_of_clinic(id):
    require_auth(LIST_ROLES)
    clinic = get_clinic_or_404(id)
    items = [s for s in db.screenings.values() if s["clinic_id"] == clinic["id"]]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([screening_view(s) for s in page], total, limit, offset)


@bp.get("/outreach-screenings")
def list_screenings():
    require_auth(LIST_ROLES)
    items = list(db.screenings.values())
    clinic_id = request.args.get("clinic_id")
    if clinic_id:
        items = [s for s in items if s["clinic_id"] == clinic_id]
    converted_application_id = request.args.get("converted_application_id")
    if converted_application_id:
        items = [s for s in items if s.get("converted_application_id") == converted_application_id]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([screening_view(s) for s in page], total, limit, offset)


@bp.get("/outreach-screenings/<screeningId>")
def get_screening(screeningId):
    require_auth(LIST_ROLES)
    s = get_screening_or_404(screeningId)
    return success_object(screening_view(s))


@bp.post("/outreach-screenings/<screeningId>/record-outcome")
def record_outcome(screeningId):
    require_auth(["OutreachPlanner"])
    s = get_screening_or_404(screeningId)
    if s["status"] != "BOOKED":
        raise invalid_state("Screening must be BOOKED to record an outcome")
    clinic = db.clinics.get(s["clinic_id"])
    if clinic is None or clinic["status"] != "IN_PROGRESS":
        raise ApiError(ERR_CLINIC_NOT_IN_PROGRESS, 409,
                       "record-outcome requires clinic IN_PROGRESS")
    s["status"] = "COMPLETED"
    touch(s)
    return success_object(screening_view(s))


@bp.post("/outreach-screenings/<screeningId>/mark-no-show")
def mark_no_show(screeningId):
    require_auth(["OutreachPlanner"])
    s = get_screening_or_404(screeningId)
    if s["status"] != "BOOKED":
        raise invalid_state("Screening must be BOOKED to mark no-show")
    s["status"] = "NO_SHOW"
    touch(s)
    clinic = db.clinics.get(s["clinic_id"])
    if clinic is not None:
        clinic["booked_screening_count"] -= 1
        touch(clinic)
    return success_object(screening_view(s))


@bp.post("/outreach-screenings/<screeningId>/rebook")
def rebook(screeningId):
    require_auth(["OutreachPlanner"])
    s = get_screening_or_404(screeningId)
    body = get_body()
    new_screening_date = req_dt(body, "new_screening_date")
    if s["status"] != "NO_SHOW":
        raise invalid_state("Screening must be NO_SHOW to rebook")
    clinic = db.clinics.get(s["clinic_id"])
    if clinic is None or clinic["status"] not in ("CONFIRMED", "IN_PROGRESS"):
        raise invalid_state("Parent clinic must be CONFIRMED or IN_PROGRESS to rebook")
    if not (parse_dt(clinic["start_date"]) <= new_screening_date <= parse_dt(clinic["end_date"])):
        raise ApiError(ERR_SCREENING_DATE_OUTSIDE_CLINIC, 409,
                       "screening_date outside the clinic's closed [start_date, end_date] interval")
    if clinic["booked_screening_count"] >= clinic["screening_capacity"]:
        raise ApiError(ERR_CLINIC_CAPACITY_REACHED, 409,
                       "booked_screening_count == screening_capacity")
    s["status"] = "BOOKED"
    s["screening_date"] = iso_date(new_screening_date)
    touch(s)
    clinic["booked_screening_count"] += 1
    touch(clinic)
    return success_object(screening_view(s))
