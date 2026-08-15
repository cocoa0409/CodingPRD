"""Volunteers: self-application, reads, list (PRD §3.4)."""

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from derived import volunteer_view
from envelope import ok_object
from errors import raise_err, ERR_NOT_FOUND, ERR_FORBIDDEN
from routes.common import paginate, guard_program_writable
from util import age_in_years
from validate import Field, get_body, validate_body

bp = Blueprint("volunteers", __name__)

_CREATE_SPEC = {
    "program_id": Field("str", required=True),
    "full_name": Field("str", required=True),
    "email": Field("str", required=True),
    "phone": Field("str", required=True),
    "birth_date": Field("date", required=True),
    "family_id": Field("str", nullable=True, default=None),
}

_READ_ROLES = ("ProgramDirector", "RegistrationCoordinator", "VolunteerCoordinator",
               "SafetyOfficer", "Volunteer")


def get_volunteer_or_404(volunteer_id):
    vol = store.get("volunteers", volunteer_id)
    if vol is None:
        raise_err(ERR_NOT_FOUND, "volunteer not found")
    return vol


@bp.post("/vbs/volunteers")
def create_volunteer():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "Anonymous")
    program = store.get("programs", data["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    if data["family_id"] is not None and store.get("families", data["family_id"]) is None:
        raise_err(ERR_NOT_FOUND, "family not found")
    guard_program_writable(program)
    is_minor = age_in_years(data["birth_date"], program["start_date"]) < 18
    volunteer = store.new_record(
        program_id=program["id"],
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        birth_date=data["birth_date"],
        family_id=data["family_id"],
        is_minor=is_minor,
        status="APPLIED",
    )
    store.put("volunteers", volunteer)
    return ok_object(volunteer_view(volunteer), status=201)


@bp.get("/vbs/volunteers/<volunteer_id>")
def get_volunteer(volunteer_id):
    ctx = authenticate()
    require_role(ctx, *_READ_ROLES)
    vol = store.get("volunteers", volunteer_id)
    if vol is not None and ctx.role == "Volunteer" and vol["id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "volunteers may only read their own record")
    if vol is None:
        raise_err(ERR_NOT_FOUND, "volunteer not found")
    return ok_object(volunteer_view(vol))


@bp.get("/vbs/volunteers")
def list_volunteers():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "VolunteerCoordinator", "SafetyOfficer")
    items = list(store.all_of("volunteers"))
    program_id = request.args.get("program_id")
    family_id = request.args.get("family_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [v for v in items if v["program_id"] == program_id]
    if family_id is not None:
        items = [v for v in items if v["family_id"] == family_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paginate(items, volunteer_view)
