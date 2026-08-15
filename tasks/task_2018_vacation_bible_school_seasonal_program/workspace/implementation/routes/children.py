"""Children: register into a family, read, list (PRD §3.2)."""

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from derived import child_view
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_FAMILY_ARCHIVED,
    ERR_FORBIDDEN,
)
from routes.common import paginate
from validate import Field, get_body, validate_body

bp = Blueprint("children", __name__)

GRADES = {
    "PRE_K", "KINDERGARTEN", "GRADE_1", "GRADE_2",
    "GRADE_3", "GRADE_4", "GRADE_5", "GRADE_6",
}

_CREATE_SPEC = {
    "family_id": Field("str", required=True),
    "first_name": Field("str", required=True),
    "last_name": Field("str", required=True),
    "birth_date": Field("date", required=True),
    "grade_completed": Field("enum", enum=GRADES, required=True),
    "has_special_needs": Field("bool", default=False),
    "allergy_summary": Field("str", default=""),
}

_READ_ROLES = ("ProgramDirector", "RegistrationCoordinator", "SafetyOfficer", "CheckInStaff", "Parent")


def get_child_or_404(child_id):
    child = store.get("children", child_id)
    if child is None:
        raise_err(ERR_NOT_FOUND, "child not found")
    return child


def check_child_ownership(ctx, child):
    if ctx.role == "Parent" and child["family_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only access their own children")


@bp.post("/vbs/children")
def create_child():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "Parent", "RegistrationCoordinator")
    # P2 ownership: a Parent may only file against their own family id.
    if ctx.role == "Parent" and data["family_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only register children into their own family")
    family = store.get("families", data["family_id"])
    if family is None:
        raise_err(ERR_NOT_FOUND, "family not found")
    if family["status"] != "ACTIVE":
        raise_err(ERR_FAMILY_ARCHIVED, "family is archived")
    child = store.new_record(
        family_id=family["id"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        birth_date=data["birth_date"],
        grade_completed=data["grade_completed"],
        has_special_needs=data["has_special_needs"],
        allergy_summary=data["allergy_summary"],
    )
    store.put("children", child)
    return ok_object(child_view(child), status=201)


@bp.get("/vbs/children/<child_id>")
def get_child(child_id):
    ctx = authenticate()
    require_role(ctx, *_READ_ROLES)
    child = store.get("children", child_id)
    if child is not None:
        check_child_ownership(ctx, child)
    if child is None:
        raise_err(ERR_NOT_FOUND, "child not found")
    return ok_object(child_view(child))


@bp.get("/vbs/children")
def list_children():
    ctx = authenticate()
    require_role(ctx, *_READ_ROLES)
    items = list(store.all_of("children"))
    family_id = request.args.get("family_id")
    if ctx.role == "Parent":
        # Parents see only their own family, regardless of the filter passed.
        items = [c for c in items if c["family_id"] == ctx.user_id]
        if family_id is not None and family_id != ctx.user_id:
            items = []
    elif family_id is not None:
        items = [c for c in items if c["family_id"] == family_id]
    return paginate(items, child_view)
