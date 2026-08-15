"""Families: self-registration, reads, soft-delete archive cascade (PRD §3.2)."""

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from cascade import cancel_registration
from derived import family_view
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_EMAIL,
    ERR_FORBIDDEN,
)
from routes.common import paginate, empty_body
from validate import Field, get_body, validate_body

bp = Blueprint("families", __name__)

_CREATE_SPEC = {
    "household_name": Field("str", required=True),
    "primary_contact_name": Field("str", required=True),
    "email": Field("str", required=True),
    "phone": Field("str", required=True),
    "preferred_contact": Field("enum", enum={"EMAIL", "PHONE", "TEXT"}, default="EMAIL"),
}


def get_family_or_404(family_id):
    family = store.get("families", family_id)
    if family is None:
        raise_err(ERR_NOT_FOUND, "family not found")
    return family


@bp.post("/vbs/families")
def create_family():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "Anonymous")
    for other in store.all_of("families"):
        if other["email"] == data["email"]:
            raise_err(ERR_DUPLICATE_EMAIL, "family email already in use")
    family = store.new_record(
        household_name=data["household_name"],
        primary_contact_name=data["primary_contact_name"],
        email=data["email"],
        phone=data["phone"],
        preferred_contact=data["preferred_contact"],
        status="ACTIVE",
    )
    store.put("families", family)
    return ok_object(family_view(family), status=201)


@bp.get("/vbs/families/<family_id>")
def get_family(family_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "SafetyOfficer", "Parent")
    family = store.get("families", family_id)
    if family is not None and ctx.role == "Parent" and family["id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only read their own family")
    if family is None:
        raise_err(ERR_NOT_FOUND, "family not found")
    return ok_object(family_view(family))


@bp.get("/vbs/families")
def list_families():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    items = list(store.all_of("families"))
    email = request.args.get("email")
    if email is not None:
        items = [f for f in items if f["email"] == email]
    include_archived = (request.args.get("include_archived") or "").lower() in (
        "true", "1", "yes",
    )
    if not include_archived:
        items = [f for f in items if f["status"] != "ARCHIVED"]
    return paginate(items, family_view)


@bp.post("/vbs/families/<family_id>/archive")
def archive_family(family_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "RegistrationCoordinator")
    family = get_family_or_404(family_id)
    if family["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "family is not ACTIVE")
    family["status"] = "ARCHIVED"
    store.touch(family)
    children = [c for c in store.all_of("children") if c["family_id"] == family["id"]]
    for child in sorted(children, key=lambda c: c["_seq"]):
        regs = [
            r
            for r in store.all_of("registrations")
            if r["child_id"] == child["id"]
            and r["status"] in ("ENROLLED", "WAITLISTED", "OFFERED")
        ]
        for reg in sorted(regs, key=lambda r: r["_seq"]):
            cancel_registration(reg, "ADMIN")
    return ok_object(family_view(family))
