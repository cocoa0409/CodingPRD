"""SpecialtyProgram endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_PROGRAM_NOT_FOUND, ERR_HOSPITAL_NOT_OPEN,
                    bad_request, invalid_state)
from helpers import (get_body, new_id, now_iso, opt_bool, req_enum, req_int,
                     touch)
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.hospitals import get_hospital_or_404, ALL_ROLES
from views import program_view

bp = Blueprint("programs", __name__)

PROGRAM_CATEGORIES = {"ORTHOPEDIC", "BURN", "CLEFT_CRANIOFACIAL",
                      "SPINAL_CORD", "NEUROMUSCULAR"}


def get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if p is None:
        raise ApiError(ERR_PROGRAM_NOT_FOUND, 404, "Program id does not exist")
    return p


@bp.post("/hospitals/<id>/programs")
def create_program(id):
    require_auth(["NetworkAdmin"])
    h = get_hospital_or_404(id)
    body = get_body()
    category = req_enum(body, "category", PROGRAM_CATEGORIES)
    accepts_international = opt_bool(body, "accepts_international", False)
    min_age_months = req_int(body, "min_age_months", minimum=0)
    max_age_months = req_int(body, "max_age_months")
    if max_age_months <= min_age_months:
        raise bad_request("max_age_months must be greater than min_age_months")
    staged_care_required = opt_bool(body, "staged_care_required", False)
    now = now_iso()
    p = {
        "id": new_id(),
        "hospital_id": h["id"],
        "category": category,
        "accepts_international": accepts_international,
        "min_age_months": min_age_months,
        "max_age_months": max_age_months,
        "staged_care_required": staged_care_required,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.programs[p["id"]] = p
    return success_object(program_view(p), 201)


@bp.get("/hospitals/<id>/programs")
def list_programs(id):
    require_auth(ALL_ROLES)
    h = get_hospital_or_404(id)
    items = [p for p in db.programs.values() if p["hospital_id"] == h["id"]]
    category = request.args.get("category")
    if category:
        items = [p for p in items if p["category"] == category]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([program_view(p) for p in page], total, limit, offset)


@bp.get("/programs/<programId>")
def get_program(programId):
    require_auth(ALL_ROLES)
    p = get_program_or_404(programId)
    return success_object(program_view(p))


@bp.post("/programs/<programId>/suspend")
def suspend_program(programId):
    require_auth(["NetworkAdmin"])
    p = get_program_or_404(programId)
    if p["status"] != "ACTIVE":
        raise invalid_state("Program must be ACTIVE to suspend")
    p["status"] = "SUSPENDED"
    touch(p)
    return success_object(program_view(p))


@bp.post("/programs/<programId>/reactivate")
def reactivate_program(programId):
    require_auth(["NetworkAdmin"])
    p = get_program_or_404(programId)
    if p["status"] != "SUSPENDED":
        raise invalid_state("Program must be SUSPENDED to reactivate")
    h = db.hospitals.get(p["hospital_id"])
    if h is None or h["status"] != "OPEN":
        raise ApiError(ERR_HOSPITAL_NOT_OPEN, 409,
                       "Hospital must be OPEN to reactivate a program")
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(program_view(p))
