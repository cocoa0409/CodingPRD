"""Housing facility endpoints (PRD §2.6, §3.4)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    get_or_404, recompute_facility_beds, serialize_assignment, serialize_facility,
    serialize_facility as _serialize_facility,
)

bp = Blueprint("facilities", __name__)

TIERS = {"ON_CAMPUS", "PARTNER_CLASS_A", "PARTNER_CLASS_B", "PARTNER_CLASS_C"}


def derive_facility_flags(facility):
    tier = facility["tier"]
    facility["is_on_campus"] = tier == "ON_CAMPUS"
    facility["is_partner_site"] = tier != "ON_CAMPUS"
    facility["immunosuppression_capable"] = tier in ("ON_CAMPUS", "PARTNER_CLASS_A")
    facility["is_step_down_capable"] = tier in ("PARTNER_CLASS_A", "PARTNER_CLASS_B")
    return facility


@bp.post("/programs/housing-facilities")
def create_facility():
    require_role("HousingCoordinator")
    data = body_json()
    facility_code = required(data, "facility_code", "str")
    name = required(data, "name", "str")
    tier = required(data, "tier", "str")
    if tier not in TIERS:
        raise ApiError("ERR_INVALID_REQUEST")
    total_beds = required(data, "total_beds", "int")
    if total_beds <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    buffer_beds = optional(data, "buffer_beds", 0, "int")
    if buffer_beds < 0:
        raise ApiError("ERR_INVALID_REQUEST")

    for existing in DB["housing_facilities"].values():
        if existing["facility_code"] == facility_code:
            raise ApiError("ERR_DUPLICATE_ENTITY")

    facility = new_row({
        "facility_code": facility_code,
        "name": name,
        "tier": tier,
        "is_on_campus": False,
        "is_partner_site": False,
        "immunosuppression_capable": False,
        "is_step_down_capable": False,
        "total_beds": total_beds,
        "buffer_beds": buffer_beds,
        "active_beds_committed": 0,
        "status": "OPEN",
    })
    derive_facility_flags(facility)
    recompute_facility_beds(facility)
    DB["housing_facilities"][facility["id"]] = facility
    return success_object(serialize_facility(facility), 201)


@bp.get("/programs/housing-facilities")
def list_facilities():
    require_role("Any")
    tier = arg("tier")
    status = arg("status")
    rows = ordered(DB["housing_facilities"].values())
    rows = filtered(rows, tier=tier, status=status)
    return list_response(rows, serialize_facility)


@bp.get("/programs/housing-facilities/<facility_id>")
def get_facility(facility_id):
    require_role("Any")
    facility = get_or_404("housing_facilities", facility_id)
    recompute_facility_beds(facility)
    return success_object(serialize_facility(facility), 200)


@bp.get("/programs/housing-facilities/<facility_id>/assignments")
def list_facility_assignments(facility_id):
    require_role("Any")
    get_or_404("housing_facilities", facility_id)
    status = arg("status")
    rows = ordered([a for a in DB["housing_assignments"].values()
                    if a["housing_facility_id"] == facility_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_assignment)


@bp.post("/programs/housing-facilities/<facility_id>/suspend")
def suspend_facility(facility_id):
    require_role("HousingCoordinator")
    facility = get_or_404("housing_facilities", facility_id)
    body_json()
    facility["status"] = "SUSPENDED"
    touch(facility)
    return success_object(serialize_facility(facility), 200)


@bp.post("/programs/housing-facilities/<facility_id>/close")
def close_facility(facility_id):
    require_role("HousingCoordinator")
    facility = get_or_404("housing_facilities", facility_id)
    body_json()
    facility["status"] = "CLOSED"
    touch(facility)
    return success_object(serialize_facility(facility), 200)


@bp.post("/programs/housing-facilities/<facility_id>/reopen")
def reopen_facility(facility_id):
    require_role("HousingCoordinator")
    facility = get_or_404("housing_facilities", facility_id)
    facility["status"] = "OPEN"
    touch(facility)
    return success_object(serialize_facility(facility), 200)