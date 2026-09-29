"""Appurtenances, commissioning documentation and the in-service schedule
(PRD 3.9)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import (ALL_ROLES, AUTHORIZED_INSPECTOR, ERECTION_SUPERINTENDENT,
                  PROJECT_ENGINEER, acting_user, endpoint)
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import (APPURTENANCES, COMMISSIONING_PACKAGES, SHELL_COURSES, TANKS,
                   new_row, touch)
from util import D, now_logical

bp = Blueprint("final", __name__)

APPURTENANCE_TYPES = ("NOZZLE", "MANWAY", "STAIRWAY", "MIXER", "ROOF_VENT")
DOCUMENT_TYPES = tuple(derive.REQUIRED_DOCUMENT_TYPES
                       + derive.OPTIONAL_DOCUMENT_TYPES)
REVIEW_DECISIONS = ("ACCEPT", "RETURN")


@bp.post("/appurtenances")
@endpoint((PROJECT_ENGINEER,))
def create_appurtenance():
    body = g.body
    tank_id = v.s_str(body, "tank_id", required=True)
    course_id = v.s_str(body, "host_shell_course_id", required=True)
    appurtenance_type = v.s_enum(body, "appurtenance_type",
                                 APPURTENANCE_TYPES, required=True)
    nominal_size = v.s_num(body, "nominal_size_in", required=True, gt=0)
    elevation = v.s_num(body, "elevation_ft", required=True, ge=0)
    azimuth = v.s_num(body, "azimuth_deg", required=True, ge=0, lt=360)
    reinforcement = v.s_bool(body, "reinforcement_required", required=False,
                             default=False)
    tank = common.get_tank(tank_id)
    course = common.get_shell_course(course_id)

    if course["tank_id"] != tank["id"]:
        raise common.cross_tank(
            "host_shell_course_id must belong to the same tank.")

    for other in derive.appurtenances_of_tank(tank["id"]):
        if (other["host_shell_course_id"] == course["id"]
                and other["appurtenance_type"] == appurtenance_type
                and D(other["azimuth_deg"]) == D(azimuth)):
            raise common.duplicate(
                "appurtenance_type and azimuth_deg must be unique within the "
                "host shell course.")

    appurtenance = new_row({
        "tank_id": tank["id"],
        "host_shell_course_id": course["id"],
        "appurtenance_type": appurtenance_type,
        "nominal_size_in": nominal_size,
        "elevation_ft": elevation,
        "azimuth_deg": azimuth,
        "reinforcement_required": reinforcement,
        "required_clearance_deg": derive.required_clearance(appurtenance_type,
                                                            nominal_size),
        "status": "DESIGNED",
        "installed_at_utc": None,
    })
    APPURTENANCES[appurtenance["id"]] = appurtenance
    return object_response(appurtenance, 201)


@bp.get("/appurtenances")
@endpoint(ALL_ROLES)
def list_appurtenances():
    filters = query_filters("tank_id", "host_shell_course_id",
                            "appurtenance_type", "status")
    rows, limit, offset, total = paged(APPURTENANCES.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/appurtenances/<appurtenance_id>")
@endpoint(ALL_ROLES)
def read_appurtenance(appurtenance_id):
    return object_response(common.get_appurtenance(appurtenance_id))


@bp.post("/appurtenances/<appurtenance_id>/installation")
@endpoint((ERECTION_SUPERINTENDENT,))
def install_appurtenance(appurtenance_id):
    appurtenance = common.get_appurtenance(appurtenance_id)
    installed_at = v.s_dt(g.body, "installed_at_utc", required=False)
    tank = TANKS.get(appurtenance["tank_id"])
    course = SHELL_COURSES.get(appurtenance["host_shell_course_id"])

    if appurtenance["status"] != "DESIGNED":
        raise ApiError(errors.ERR_APPURTENANCE_STATE_INVALID, 409,
                       "Only a DESIGNED appurtenance may be installed.")
    common.require_not_frozen(tank)

    if course is None or course["status"] != "RT_ACCEPTED":
        raise ApiError(errors.ERR_HOST_COURSE_NOT_ACCEPTED, 409,
                       "The host shell course is not RT_ACCEPTED.")
    if derive.clearance_conflict(appurtenance):
        raise ApiError(errors.ERR_APPURTENANCE_CLEARANCE_VIOLATION, 409,
                       "The angular clearance envelope of an installed "
                       "neighbour would be violated.")

    appurtenance["status"] = "INSTALLED"
    appurtenance["installed_at_utc"] = (installed_at if installed_at is not None
                                        else now_logical())
    touch(appurtenance)
    return object_response(appurtenance)


@bp.post("/commissioning-packages")
@endpoint((PROJECT_ENGINEER,))
def create_commissioning_package():
    tank_id = v.s_str(g.body, "tank_id", required=True)
    tank = common.get_tank(tank_id)

    if derive.package_of_tank_commissioning(tank["id"]) is not None:
        raise ApiError(errors.ERR_SINGLETON_EXISTS, 409,
                       "The tank already has a commissioning package.")

    package = new_row({
        "tank_id": tank["id"],
        "required_document_types": list(derive.REQUIRED_DOCUMENT_TYPES),
        "submitted_document_types": [],
        "missing_document_types": list(derive.REQUIRED_DOCUMENT_TYPES),
        "document_count": 0,
        "deficiency_count": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "bottom_remaining_life_years": None,
        "internal_inspection_interval_years": None,
        "external_inspection_interval_years": None,
        "next_internal_due_utc": None,
        "next_external_due_utc": None,
        "accepted_at_utc": None,
    })
    package["_documents"] = []
    COMMISSIONING_PACKAGES[package["id"]] = package
    return object_response(package, 201)


@bp.get("/commissioning-packages")
@endpoint(ALL_ROLES)
def list_commissioning_packages():
    filters = query_filters("tank_id", "status")
    rows, limit, offset, total = paged(COMMISSIONING_PACKAGES.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/commissioning-packages/<commissioning_package_id>")
@endpoint(ALL_ROLES)
def read_commissioning_package(commissioning_package_id):
    return object_response(
        common.get_commissioning_package(commissioning_package_id))


@bp.post("/commissioning-packages/<commissioning_package_id>/documents")
@endpoint((PROJECT_ENGINEER,))
def record_document(commissioning_package_id):
    package = common.get_commissioning_package(commissioning_package_id)
    document_type = v.s_enum(g.body, "document_type", DOCUMENT_TYPES,
                             required=True)
    reference_number = v.s_str(g.body, "reference_number", required=True)

    if package["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError(errors.ERR_PACKAGE_STATE_INVALID, 409,
                       "Documents may only be attached to a DRAFT or "
                       "RETURNED_FOR_CORRECTION package.")

    package.setdefault("_documents", []).append({
        "document_type": document_type,
        "reference_number": reference_number,
    })
    derive.refresh_documents(package)
    touch(package)
    return object_response(package)


@bp.post("/commissioning-packages/<commissioning_package_id>/submission")
@endpoint((PROJECT_ENGINEER,))
def submit_package(commissioning_package_id):
    package = common.get_commissioning_package(commissioning_package_id)
    v.s_str(g.body, "remarks", required=False)
    tank = TANKS.get(package["tank_id"])

    if package["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError(errors.ERR_PACKAGE_STATE_INVALID, 409,
                       "Only a DRAFT or RETURNED_FOR_CORRECTION package may "
                       "be submitted.")
    if tank["construction_phase"] != "COATED":
        raise ApiError(errors.ERR_PACKAGE_STATE_INVALID, 409,
                       "The tank must be COATED.")
    common.require_posture_open(tank)

    designed = [a for a in derive.appurtenances_of_tank(tank["id"])
                if a["status"] != "INSTALLED"]
    if designed:
        raise ApiError(errors.ERR_APPURTENANCES_NOT_INSTALLED, 409,
                       "Every appurtenance of the tank must be INSTALLED.")
    if package["missing_document_types"]:
        raise ApiError(errors.ERR_MISSING_COMMISSIONING_DOCUMENTS, 409,
                       "Every required commissioning document must be "
                       "recorded.")

    package["status"] = "SUBMITTED"
    package["submitted_by_user_id"] = acting_user()
    touch(package)
    return object_response(package)


@bp.post("/commissioning-packages/<commissioning_package_id>/review")
@endpoint((AUTHORIZED_INSPECTOR,))
def review_package(commissioning_package_id):
    package = common.get_commissioning_package(commissioning_package_id)
    decision = v.s_enum(g.body, "decision", REVIEW_DECISIONS, required=True)
    v.s_str(g.body, "remarks", required=False)
    tank = TANKS.get(package["tank_id"])

    if package["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_PACKAGE_STATE_INVALID, 409,
                       "Only a SUBMITTED package may be reviewed.")
    if decision == "ACCEPT":
        common.require_posture_open(tank)
    if package["submitted_by_user_id"] == acting_user():
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "The operator who submitted the package may not review "
                       "it.")

    if decision == "ACCEPT":
        accepted_at = now_logical()
        package["status"] = "ACCEPTED"
        package["reviewed_by_user_id"] = acting_user()
        derive.compute_in_service_schedule(package, tank, accepted_at)
        touch(package)
        if tank["construction_phase"] == "COATED":
            tank["construction_phase"] = "COMMISSIONED"
            touch(tank)
    else:
        package["status"] = "RETURNED_FOR_CORRECTION"
        package["deficiency_count"] = int(package["deficiency_count"]) + 1
        package["reviewed_by_user_id"] = acting_user()
        touch(package)
    return object_response(package)
