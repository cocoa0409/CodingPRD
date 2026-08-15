"""Insurance enrollment endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso, get_clock
from middleware import get_auth, require_role, check_student_ownership
from response import success_object, success_list
from utils import require_string, parse_dt, parse_pagination
from errors import (
    not_found, invalid_request, invalid_state, ApiError,
    ERR_TRAVEL_ADVISORY_BLOCK, ERR_COVERAGE_WINDOW_INSUFFICIENT,
    ERR_DUPLICATE_ENROLLMENT, ERR_CANNOT_CANCEL_WHILE_ABROAD,
)
from services.program import active_blocking_advisory

bp = Blueprint("insurance_enrollments", __name__)


@bp.route("/api/v1/insurance-enrollments", methods=["POST"])
def create_insurance_enrollment():
    user_id, role = get_auth()
    require_role(role, ["Student"])

    body = request.get_json(silent=True) or {}
    application_id = require_string(body, "application_id")
    provider = require_string(body, "provider")
    coverage_start_date = require_string(body, "coverage_start_date")
    coverage_end_date = require_string(body, "coverage_end_date")

    cs = parse_dt(coverage_start_date, "coverage_start_date")
    ce = parse_dt(coverage_end_date, "coverage_end_date")
    if not cs < ce:
        raise invalid_request("coverage_start_date must be strictly before coverage_end_date")

    app = db.applications.get(application_id)
    if not app:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, app["student_id"])

    # state gate: application must be COMMITTED
    if app["status"] != "COMMITTED":
        raise invalid_state("Application is not in COMMITTED status")

    program = db.programs.get(app["program_id"])
    if not program:
        raise not_found("Program not found")

    # travel-warning gate (tier 7)
    clock = parse_dt(get_clock(), "clock")
    prog_start = parse_dt(program["start_date"], "start_date")
    prog_end = parse_dt(program["end_date"], "end_date")
    if active_blocking_advisory(program["country_code"], clock, prog_start, prog_end):
        raise ApiError(ERR_TRAVEL_ADVISORY_BLOCK, "Travel advisory blocks insurance enrollment", 422)

    # coverage containment (tier 8 temporal)
    if not (cs <= prog_start and ce >= prog_end):
        raise ApiError(ERR_COVERAGE_WINDOW_INSUFFICIENT, "Coverage window does not fully contain the program dates", 422)

    # duplicate ACTIVE enrollment (tier 10)
    for enr in db.insurance_enrollments.values():
        if enr["application_id"] == app["id"] and enr["status"] == "ACTIVE":
            raise ApiError(ERR_DUPLICATE_ENROLLMENT, "An ACTIVE insurance enrollment already exists for the application", 409)

    ts = now_iso()
    rec = {
        "id": new_id(),
        "application_id": app["id"],
        "provider": provider,
        "coverage_start_date": coverage_start_date,
        "coverage_end_date": coverage_end_date,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.insurance_enrollments[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/insurance-enrollments", methods=["GET"])
def list_insurance_enrollments():
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator", "BursarOffice", "Student"])

    limit, offset = parse_pagination(request.args)
    application_id = request.args.get("application_id")
    status = request.args.get("status")

    items = list(db.insurance_enrollments.values())
    if application_id is not None:
        items = [e for e in items if e["application_id"] == application_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]

    # Student role: only own application's enrollments
    if role == "Student":
        items = [
            e for e in items
            if db.applications.get(e["application_id"])
            and db.applications[e["application_id"]]["student_id"] == user_id
        ]

    items.sort(key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(e) for e in page], limit, offset, total)


@bp.route("/api/v1/insurance-enrollments/<id>", methods=["GET"])
def get_insurance_enrollment(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator", "BursarOffice", "Student"])

    rec = db.insurance_enrollments.get(id)
    if not rec:
        raise not_found("InsuranceEnrollment not found")

    if role == "Student":
        app = db.applications.get(rec["application_id"])
        if not app or app["student_id"] != user_id:
            from errors import forbidden
            raise forbidden("Student may only access own application's enrollments")

    return success_object(dict(rec), 200)


@bp.route("/api/v1/insurance-enrollments/<id>/cancel", methods=["POST"])
def cancel_insurance_enrollment(id):
    user_id, role = get_auth()
    require_role(role, ["Student", "ProgramCoordinator"])

    rec = db.insurance_enrollments.get(id)
    if not rec:
        raise not_found("InsuranceEnrollment not found")

    app = db.applications.get(rec["application_id"])
    if role == "Student":
        if not app or app["student_id"] != user_id:
            from errors import forbidden
            raise forbidden("Student may only cancel own application's enrollments")

    if rec["status"] != "ACTIVE":
        raise invalid_state("InsuranceEnrollment is not in ACTIVE status")

    # safety lock (tier 7): cannot cancel while application ABROAD
    if app and app["status"] == "ABROAD":
        raise ApiError(ERR_CANNOT_CANCEL_WHILE_ABROAD, "Cannot cancel insurance while the application is ABROAD", 422)

    rec["status"] = "CANCELLED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)
