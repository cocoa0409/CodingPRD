"""Shelter site registration, inspection and site-scoped shelter listings."""

import calc
import core
from core import (authenticate, base_row, insert, list_response, must_get,
                  ok_object, read_json, rows, serialize, touch, validate_body,
                  validate_enum)
from errors import ApiError
from flask import Blueprint

bp = Blueprint("site", __name__)

SITE_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager"]
ACCESSIBILITY = ("FULL", "PARTIAL", "NONE")
INSPECTION_RESULTS = ("PASS", "CONDITIONAL_PASS", "FAIL")


@bp.post("/api/v1/shelter-sites")
def create_shelter_site():
    authenticate(["NationalHQAdmin", "RegionalCoordinator"])
    body = read_json()
    validate_body(body, required={
        "facility_name": str,
        "address_line": str,
        "region_id": str,
        "capacity_beds": int,
        "accessibility_rating": str,
        "functional_needs_support": bool,
        "generator_onsite": bool,
        "agreement_expires_at": "instant",
    })
    validate_enum("accessibility_rating", body["accessibility_rating"], ACCESSIBILITY)
    if body["capacity_beds"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity_beds must be >= 1")
    must_get("regions", body["region_id"])
    record = base_row()
    record.update({
        "facility_name": body["facility_name"],
        "address_line": body["address_line"],
        "region_id": body["region_id"],
        "capacity_beds": body["capacity_beds"],
        "accessibility_rating": body["accessibility_rating"],
        "functional_needs_support": body["functional_needs_support"],
        "generator_onsite": body["generator_onsite"],
        "agreement_expires_at": core.iso_of(body["agreement_expires_at"]),
        "agreement_status": "PENDING_INSPECTION",
        "capacity_verified_beds": 0,
        "accessibility_verified": False,
        "functional_needs_verified": False,
        "last_inspection_at": None,
        "inspection_result": None,
    })
    insert("shelter_sites", record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/shelter-sites/<site_id>")
def read_shelter_site(site_id):
    authenticate(SITE_ROLES)
    return ok_object(serialize(must_get("shelter_sites", site_id)))


@bp.get("/api/v1/shelter-sites/<site_id>/shelter-operations")
def site_shelter_operations(site_id):
    authenticate(SITE_ROLES)
    site = must_get("shelter_sites", site_id)
    children = [s for s in rows("shelter_operations") if s["shelter_site_id"] == site["id"]]
    return list_response(children)


@bp.post("/api/v1/shelter-sites/<site_id>/inspections")
def record_inspection(site_id):
    authenticate(["NationalHQAdmin", "RegionalCoordinator"])
    body = read_json()
    validate_body(body, required={
        "expected_shelter_site_version": int,
        "inspected_at": "instant",
        "inspector_user_id": str,
        "capacity_verified_beds": int,
        "accessibility_verified": bool,
        "functional_needs_verified": bool,
        "deficiency_count": int,
        "result": str,
    })
    validate_enum("result", body["result"], INSPECTION_RESULTS)
    site = must_get("shelter_sites", site_id)
    if body["expected_shelter_site_version"] != site["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "the shelter site version is stale")
    if site["agreement_status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the shelter agreement has expired")

    result = body["result"]
    if result in ("PASS", "CONDITIONAL_PASS"):
        if site["agreement_status"] != "APPROVED":
            if body["capacity_verified_beds"] < 1 or not body["accessibility_verified"]:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "a passing inspection requires a verified bed count and accessibility")
            site["agreement_status"] = "APPROVED"
    else:
        site["agreement_status"] = "SUSPENDED"

    site["capacity_verified_beds"] = body["capacity_verified_beds"]
    site["accessibility_verified"] = body["accessibility_verified"]
    site["functional_needs_verified"] = body["functional_needs_verified"]
    site["last_inspection_at"] = core.iso_of(body["inspected_at"])
    site["inspection_result"] = result
    touch(site)

    if result == "FAIL":
        for shelter in rows("shelter_operations"):
            if shelter["shelter_site_id"] == site["id"] and shelter["posture"] in ("OPEN", "RESTRICTED"):
                shelter["posture"] = "RESTRICTED"
                touch(shelter)
                operation = must_get("disaster_relief_operations",
                                     shelter["disaster_relief_operation_id"])
                calc.refresh_operation(operation)
    return ok_object(serialize(site), 201)
