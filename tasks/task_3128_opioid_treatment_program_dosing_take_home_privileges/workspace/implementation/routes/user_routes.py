"""Users (PRD 3.15)."""
from flask import Blueprint, request

import db
from constants import STAFF_ROLES
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context
from services import entity
from validation import text_field

bp = Blueprint("users", __name__)

READ_ROLES = ["ProgramAdministrator", "Physician", "Nurse", "MedicalDirector", "RegulatoryAuditor"]
FULL_READ_ROLES = READ_ROLES + ["Counselor"]
LICENSED_ROLES = ("PHYSICIAN", "NURSE", "MEDICAL_DIRECTOR")


@bp.route("/otp/users", methods=["POST"])
def create_user():
    context(["ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    full_name = text_field(body, "full_name")
    staff_role = text_field(body, "staff_role")
    if staff_role not in STAFF_ROLES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "staff_role must be one of %s" % ", ".join(STAFF_ROLES),
        )
    license_number = body.get("license_number")
    if license_number is not None:
        license_number = str(license_number).strip() or None
    if staff_role in LICENSED_ROLES and not license_number:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "license_number is required for %s" % staff_role,
        )
    program_id = body.get("program_id")
    if program_id:
        if program_id not in db.programs:
            raise ApiError("ERR_PROGRAM_NOT_FOUND", "No Program with the supplied id")
    row = entity.make_user(
        {
            "program_id": program_id,
            "full_name": full_name,
            "staff_role": staff_role,
            "license_number": license_number,
        }
    )
    db.users[row["id"]] = row
    return ok_object(entity.serialize_user(row), 201)


@bp.route("/otp/users", methods=["GET"])
def list_users():
    context(READ_ROLES)
    program_id = request.args.get("program_id")
    rows = list(db.users.values())
    if program_id:
        rows = [r for r in rows if r.get("program_id") == program_id]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_user(r) for r in page], limit, offset, total)


@bp.route("/otp/users/<user_id>", methods=["GET"])
def read_user(user_id):
    context(FULL_READ_ROLES)
    row = db.users.get(user_id)
    if row is None:
        raise ApiError("ERR_USER_NOT_FOUND", "No User with the supplied id")
    return ok_object(entity.serialize_user(row))