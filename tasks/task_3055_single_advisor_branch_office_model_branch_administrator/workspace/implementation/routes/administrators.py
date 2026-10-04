"""Branch office administrator routes (§3.3)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_string, get_or_404, stamp_new, touch,
    paginate, sort_by_created_at, recompute_staffing,
)
from response import success_object, success_list

bp = Blueprint("administrators", __name__)
PREFIX = "/branch-office/administrators"


@bp.route(PREFIX, methods=["POST"])
def create_administrator():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["full_name", "email", "monthly_salary_cents"])
    name = require_string(body, "full_name")
    email = require_string(body, "email")
    salary = body["monthly_salary_cents"]
    if isinstance(salary, bool) or not isinstance(salary, int) or salary <= 0:
        raise err("ERR_INVALID_REQUEST", "monthly_salary_cents must be a positive integer.")
    for a in db.administrators.values():
        if a.get("email") == email:
            raise err("ERR_DUPLICATE", "An administrator with this email already exists.")
    adm = stamp_new({
        "full_name": name,
        "email": email,
        "monthly_salary_cents": salary,
        "branch_id": None,
        "status": "HIRED",
    })
    db.administrators[adm["id"]] = adm
    return success_object(adm, 201)


@bp.route(PREFIX, methods=["GET"])
def list_administrators():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    items = list(db.administrators.values())
    branch_id = request.args.get("branch_id")
    if branch_id:
        items = [a for a in items if a.get("branch_id") == branch_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a.get("status") == status]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<aid>", methods=["GET"])
def get_administrator(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "BranchAdministrator"})
    return success_object(get_or_404(db.administrators, aid, "BranchOfficeAdministrator"))


@bp.route(f"{PREFIX}/<aid>/place-on-leave", methods=["POST"])
def place_on_leave(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    adm = get_or_404(db.administrators, aid, "BranchOfficeAdministrator")
    if adm.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Administrator is not ACTIVE.")
    adm["status"] = "ON_LEAVE"
    touch(adm)
    branch = db.branches.get(adm.get("branch_id"))
    if branch is not None:
        recompute_staffing(branch)
        touch(branch)
    return success_object(adm)


@bp.route(f"{PREFIX}/<aid>/return-from-leave", methods=["POST"])
def return_from_leave(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    adm = get_or_404(db.administrators, aid, "BranchOfficeAdministrator")
    if adm.get("status") != "ON_LEAVE":
        raise err("ERR_INVALID_STATE", "Administrator is not ON_LEAVE.")
    adm["status"] = "ACTIVE"
    touch(adm)
    branch = db.branches.get(adm.get("branch_id"))
    if branch is not None:
        recompute_staffing(branch)
        touch(branch)
    return success_object(adm)


@bp.route(f"{PREFIX}/<aid>/release", methods=["POST"])
def release_administrator(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    adm = get_or_404(db.administrators, aid, "BranchOfficeAdministrator")
    if adm.get("status") not in ("ACTIVE", "ON_LEAVE"):
        raise err("ERR_INVALID_STATE", "Administrator is not ACTIVE or ON_LEAVE.")
    branch_id = adm.get("branch_id")
    adm["status"] = "RELEASED"
    adm["branch_id"] = None
    touch(adm)
    branch = db.branches.get(branch_id)
    if branch is not None:
        recompute_staffing(branch)
        touch(branch)
    return success_object(adm)
