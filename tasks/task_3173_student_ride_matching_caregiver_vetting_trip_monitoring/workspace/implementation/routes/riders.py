"""Rider endpoints: registration, placement updates and reverse reads."""

import calculations as calc
import db
import models
import validators as v
from errors import ERR_INVALID_REQUEST, ApiError, not_found
from flask import Blueprint, request
from middleware import actor_role, mask_phone, requires
from response import array_response, object_response, paginate

bp = Blueprint("riders", __name__)

RIDER_INPUT = (
    "district_id", "full_name", "date_of_birth", "program_type", "spi_level",
    "home_address", "school_name", "emergency_contact_phone", "authorized_adults",
    "notify_on_pickup", "notify_on_dropoff",
)

RIDER_UPDATE_INPUT = (
    "home_address", "school_name", "emergency_contact_phone", "authorized_adults",
    "notify_on_pickup", "notify_on_dropoff", "spi_level",
)


def load_rider(rider_id):
    rider = db.get("riders", rider_id)
    if rider is None:
        raise not_found("The addressed rider does not exist.")
    return rider


def _normalise_adults(raw):
    out = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, "authorized_adults entries must be objects.")
        if "name" not in entry:
            raise ApiError(ERR_INVALID_REQUEST, "each authorized_adults entry requires a name.")
        out.append({
            "name": entry.get("name"),
            "relationship": entry.get("relationship"),
            "phone": entry.get("phone"),
        })
    return out


@bp.post("/student-rides/riders")
@requires("DistrictAdmin", "PlatformAdmin")
def create_rider():
    data = v.body()
    v.reject_unknown(data, RIDER_INPUT)
    district_id = v.as_string(data, "district_id")
    if db.get("districts", district_id) is None:
        raise not_found("The addressed district does not exist.")

    phone = v.as_string(data, "emergency_contact_phone")
    rider = db.new_record({
        "district_id": district_id,
        "full_name": v.as_string(data, "full_name"),
        "date_of_birth": v.as_string(data, "date_of_birth"),
        "program_type": v.enum_value("program_type", v.required(data, "program_type")),
        "spi_level": v.as_int(data, "spi_level", default=1),
        "home_address": v.as_string(data, "home_address"),
        "school_name": v.as_string(data, "school_name"),
        "emergency_contact_phone": phone,
        "authorized_adults": _normalise_adults(v.as_array(data, "authorized_adults", default=[])),
        "notify_on_pickup": v.as_bool(data, "notify_on_pickup", default=True),
        "notify_on_dropoff": v.as_bool(data, "notify_on_dropoff", default=True),
        "support_center_phone_masked": mask_phone(phone),
        "active_ride_request_count": 0,
        "status": "ACTIVE",
    })
    db.save("riders", rider)
    return object_response(models.rider_out(rider), 201)


@bp.get("/student-rides/riders")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_riders():
    page, limit, offset, total = paginate(db.all_of("riders"), request.args)
    return array_response(models.serialise_all("riders", page), limit, offset, total)


@bp.get("/student-rides/riders/<rider_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def get_rider(rider_id):
    rider = load_rider(rider_id)
    calc.recompute_rider(rider)
    return object_response(models.rider_for_actor(rider, actor_role()))


@bp.put("/student-rides/riders/<rider_id>")
@requires("DistrictAdmin", "PlatformAdmin")
def update_rider(rider_id):
    rider = load_rider(rider_id)
    data = v.body()
    v.reject_unknown(data, RIDER_UPDATE_INPUT)
    if "home_address" in data:
        rider["home_address"] = v.as_string(data, "home_address")
    if "school_name" in data:
        rider["school_name"] = v.as_string(data, "school_name")
    if "emergency_contact_phone" in data:
        phone = v.as_string(data, "emergency_contact_phone")
        rider["emergency_contact_phone"] = phone
        rider["support_center_phone_masked"] = mask_phone(phone)
    if "authorized_adults" in data:
        rider["authorized_adults"] = _normalise_adults(v.as_array(data, "authorized_adults", default=[]))
    if "notify_on_pickup" in data:
        rider["notify_on_pickup"] = v.as_bool(data, "notify_on_pickup", default=True)
    if "notify_on_dropoff" in data:
        rider["notify_on_dropoff"] = v.as_bool(data, "notify_on_dropoff", default=True)
    if "spi_level" in data:
        rider["spi_level"] = v.as_int(data, "spi_level", default=1)
    db.touch(rider)
    return object_response(models.rider_out(rider))


@bp.get("/student-rides/riders/<rider_id>/ride-requests")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_rider_ride_requests(rider_id):
    load_rider(rider_id)
    rows = [r for r in db.all_of("ride_requests") if r["rider_id"] == rider_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("ride_requests", page), limit, offset, total)


@bp.get("/student-rides/riders/<rider_id>/trips")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_rider_trips(rider_id):
    load_rider(rider_id)
    rows = [t for t in db.all_of("trips") if t["rider_id"] == rider_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("trips", page), limit, offset, total)