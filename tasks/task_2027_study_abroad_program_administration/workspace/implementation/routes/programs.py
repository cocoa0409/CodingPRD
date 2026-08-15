"""Program endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role
from response import success_object, success_list
from utils import (
    require_string, require_int, require_number, require_enum, parse_dt, parse_pagination,
)
from errors import not_found, invalid_request, invalid_state, ApiError, ERR_AGREEMENT_NOT_ACTIVE, ERR_PROGRAM_FEE_REQUIRED
from services.program import check_schedule_buffer, recompute_seats

bp = Blueprint("programs", __name__)

TERMS = {"SPRING", "SUMMER", "FALL", "ACADEMIC_YEAR"}
BILLING_MODELS = {"HOME_TUITION", "PROGRAM_FEE"}
ALL_ROLES = ["ProgramCoordinator", "Student", "FacultyApprover", "SafetyOfficer", "BursarOffice"]


@bp.route("/api/v1/programs", methods=["POST"])
def create_program():
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    body = request.get_json(silent=True) or {}
    partner_agreement_id = require_string(body, "partner_agreement_id")
    name = require_string(body, "name")
    country_code = require_string(body, "country_code")
    host_institution = require_string(body, "host_institution")
    term = require_enum(body, "term", TERMS)
    start_date = require_string(body, "start_date")
    end_date = require_string(body, "end_date")
    application_deadline = require_string(body, "application_deadline")
    capacity = require_int(body, "capacity")
    billing_model = require_enum(body, "billing_model", BILLING_MODELS)
    min_gpa = require_number(body, "min_gpa")

    # request-body integrity checks
    if capacity < 1:
        raise invalid_request("capacity must be >= 1")
    if not (0.0 <= min_gpa <= 4.0):
        raise invalid_request("min_gpa must be between 0.0 and 4.0")

    sd = parse_dt(start_date, "start_date")
    ed = parse_dt(end_date, "end_date")
    if not sd < ed:
        raise invalid_request("start_date must be strictly before end_date")
    parse_dt(application_deadline, "application_deadline")

    # conditional fee rule (tier 4)
    program_fee_cents = body.get("program_fee_cents")
    if billing_model == "PROGRAM_FEE":
        if program_fee_cents is None or isinstance(program_fee_cents, bool) or not isinstance(program_fee_cents, int) or program_fee_cents <= 0:
            raise ApiError(ERR_PROGRAM_FEE_REQUIRED, "billing_model PROGRAM_FEE requires program_fee_cents > 0", 422)
    else:  # HOME_TUITION
        if program_fee_cents is not None and program_fee_cents != 0:
            raise invalid_request("program_fee_cents must be omitted or 0 for HOME_TUITION")
        program_fee_cents = program_fee_cents or 0

    # partner agreement must exist (tier 9 referential)
    agreement = db.partner_agreements.get(partner_agreement_id)
    if not agreement:
        raise not_found("PartnerAgreement not found")

    # schedule buffer (tier 8 temporal)
    check_schedule_buffer(host_institution, start_date, end_date)

    ts = now_iso()
    rec = {
        "id": new_id(),
        "partner_agreement_id": partner_agreement_id,
        "name": name,
        "country_code": country_code,
        "host_institution": host_institution,
        "term": term,
        "start_date": start_date,
        "end_date": end_date,
        "application_deadline": application_deadline,
        "capacity": capacity,
        "billing_model": billing_model,
        "program_fee_cents": program_fee_cents,
        "min_gpa": min_gpa,
        "seats_taken": 0,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.programs[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/programs", methods=["GET"])
def list_programs():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)

    limit, offset = parse_pagination(request.args)
    country_code = request.args.get("country_code")
    status = request.args.get("status")
    host_institution = request.args.get("host_institution")
    partner_agreement_id = request.args.get("partner_agreement_id")

    items = list(db.programs.values())
    if country_code is not None:
        items = [p for p in items if p["country_code"] == country_code]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if host_institution is not None:
        items = [p for p in items if p["host_institution"] == host_institution]
    if partner_agreement_id is not None:
        items = [p for p in items if p["partner_agreement_id"] == partner_agreement_id]

    for p in items:
        recompute_seats(p)

    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(p) for p in page], limit, offset, total)


@bp.route("/api/v1/programs/<id>", methods=["GET"])
def get_program(id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)

    rec = db.programs.get(id)
    if not rec:
        raise not_found("Program not found")
    recompute_seats(rec)
    return success_object(dict(rec), 200)


@bp.route("/api/v1/programs/<id>/publish", methods=["POST"])
def publish_program(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    rec = db.programs.get(id)
    if not rec:
        raise not_found("Program not found")

    if rec["status"] != "DRAFT":
        raise invalid_state("Program is not in DRAFT status")

    agreement = db.partner_agreements.get(rec["partner_agreement_id"])
    if not agreement:
        raise not_found("PartnerAgreement not found")
    if agreement["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Partner agreement is not ACTIVE", 422)

    rec["status"] = "OPEN"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    recompute_seats(rec)
    return success_object(dict(rec), 200)
