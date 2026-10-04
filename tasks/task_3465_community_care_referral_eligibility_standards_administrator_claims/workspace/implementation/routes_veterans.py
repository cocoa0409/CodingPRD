"""Veteran enrollment and eligibility determination (PRD section 3.2)."""
from flask import Blueprint, request

import constants as C
import db
import response
import services
import validate as v
from errors import fail
from middleware import endpoint

bp = Blueprint("veterans", __name__)


@bp.post("/community-care/veterans")
@endpoint([C.ROLE_ELIGIBILITY_CLERK])
def create_veteran(user_id, role):
    b = v.body()
    station = v.body_fk(b, "home_station_id", "care_stations", "care station")
    full_name = v.req_str(b, "full_name")
    home_station_id = v.req_str(b, "home_station_id")
    priority_group = v.req_int(b, "priority_group")
    home_latitude = v.req_number(b, "home_latitude")
    home_longitude = v.req_number(b, "home_longitude")
    if not (1 <= priority_group <= 8):
        fail("ERR_INVALID_REQUEST", "priority_group must be in 1..8")
    rec = db.create("veterans", {
        "full_name": full_name,
        "home_station_id": home_station_id,
        "priority_group": priority_group,
        "home_latitude": home_latitude,
        "home_longitude": home_longitude,
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/veterans/<rid>")
@endpoint(C.ALL_ROLES)
def get_veteran(user_id, role, rid):
    vet = v.path_entity("veterans", rid, "veteran")
    return response.ok(db.public(vet))


@bp.get("/community-care/veterans")
@endpoint(C.ALL_ROLES)
def list_veterans(user_id, role):
    preds = []
    home_station_id = request.args.get("home_station_id")
    if home_station_id is not None:
        preds.append(lambda r: r["home_station_id"] == home_station_id)
    priority_group = v.query_int("priority_group")
    if priority_group is not None:
        preds.append(lambda r: r["priority_group"] == priority_group)
    return response.list_response("veterans", preds)


@bp.post("/community-care/veterans/<rid>/eligibility-assessments")
@endpoint([C.ROLE_ELIGIBILITY_CLERK])
def create_assessment(user_id, role, rid):
    vet = v.path_entity("veterans", rid, "veteran")
    b = v.body()
    service_code = v.req_str(b, "service_code")
    service_category = v.req_enum(b, "service_category", C.SERVICE_CATEGORIES)
    geo_classification = v.req_enum(b, "geo_classification", C.GEO_CLASSIFICATIONS)
    choice_requested = v.req_bool(b, "choice_requested")
    expected_version = v.req_int(b, "expected_veteran_version")
    # OCC (stage 5): the caller's view of the veteran must be current.
    if expected_version != vet["version"]:
        fail("ERR_STALE_VERSION",
             "expected_veteran_version %s does not match current version %s"
             % (expected_version, vet["version"]))
    station = db.get("care_stations", vet["home_station_id"])
    if station is None:
        fail("ERR_NOT_FOUND", "veteran's home station does not exist")
    drive_time = services.drive_minutes(vet, station, geo_classification)
    computed = services.compute_eligibility(
        vet, station, service_code, service_category, drive_time, choice_requested)
    # Supersede the prior CURRENT assessment for the same (veteran, service_code).
    for old in db.all_recs("assessments"):
        if (old["veteran_id"] == vet["id"] and old["service_code"] == service_code
                and old["status"] == "CURRENT"):
            old["status"] = "SUPERSEDED"
            db.touch(old)
    # Supersession is a Veteran mutation: version +1 on every creation.
    db.touch(vet)
    rec = db.create("assessments", {
        "veteran_id": vet["id"],
        "service_code": service_code,
        "service_category": service_category,
        "geo_classification": geo_classification,
        "choice_requested": choice_requested,
        "drive_time_minutes": drive_time,
        "wait_days": computed["wait_days"],
        "service_available": computed["service_available"],
        "drive_standard_failed": computed["drive_standard_failed"],
        "wait_standard_failed": computed["wait_standard_failed"],
        "choice_granted": computed["choice_granted"],
        "eligible": computed["eligible"],
        "status": "CURRENT",
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/veterans/<rid>/eligibility-assessments")
@endpoint(C.ALL_ROLES)
def list_assessments(user_id, role, rid):
    v.path_entity("veterans", rid, "veteran")
    preds = [lambda r: r["veteran_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        preds.append(lambda r: r["status"] == status)
    service_code = request.args.get("service_code")
    if service_code is not None:
        preds.append(lambda r: r["service_code"] == service_code)
    return response.list_response("assessments", preds)
