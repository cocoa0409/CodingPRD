"""Employee memberships and the employment dimension (PRD 3.3)."""
from flask import Blueprint

import auth
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("memberships", __name__)


@bp.get("/perks/memberships/<row_id>")
def get_membership(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN, auth.EMPLOYEE)
    # An Employee's X-User-ID IS its membership id, so scope is decided on the
    # path identifier alone and therefore before existence.
    if principal.is_employee and row_id != principal.user_id:
        auth.deny_scope()
    row = support.fetch("memberships", row_id)
    auth.check_employer_scope(principal, row["employer_id"])
    return response.ok(derive.membership_json(row))


@bp.get("/perks/memberships")
def list_memberships():
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN)
    employer_id = support.arg("employer_id")
    source_file_id = support.arg("source_file_id")
    status = support.arg("status")
    employment_status = support.arg("employment_status")
    region = support.arg("region_code")
    rows = []
    for row in db.memberships.values():
        if principal.is_employer_admin and row["employer_id"] != principal.user_id:
            continue
        if not support.matches(row, "employer_id", employer_id):
            continue
        if not support.matches(row, "source_file_id", source_file_id):
            continue
        if not support.matches(row, "status", status):
            continue
        if not support.matches(row, "employment_status", employment_status):
            continue
        if not support.matches(row, "region_code", region):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.membership_json)


@bp.post("/perks/memberships/<row_id>/employment-status")
def write_employment_status(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN)
    row = support.fetch("memberships", row_id)
    auth.check_employer_scope(principal, row["employer_id"])
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "employment_status", "type": "enum", "required": True,
         "values": validate.EMPLOYMENT_STATUSES},
    ])
    if row["status"] == "REVOKED":
        raise ApiError("ERR_MEMBERSHIP_REVOKED",
                       "REVOKED is terminal; rehiring requires a fresh batch.")
    row["employment_status"] = data["employment_status"]
    row["last_employment_change_at"] = clock.now()
    if data["employment_status"] == "TERMINATED":
        row["status"] = "REVOKED"
        db.touch(row)
        cascade.void_pending_for_membership(row, "MEMBERSHIP_INELIGIBLE")
    else:
        db.touch(row)
    return response.ok(derive.membership_json(row))
