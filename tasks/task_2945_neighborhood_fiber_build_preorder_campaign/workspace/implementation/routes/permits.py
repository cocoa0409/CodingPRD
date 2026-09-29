"""Permit applications (PRD 3.5)."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import add_days, bump, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("permits", __name__)

READ_ROLES = ("ProgramManager", "PermitOffice", "InstallCoordinator")


@bp.post("/permit-applications")
def create_permit():
    auth.gate(("ProgramManager",))
    data = shape.body()
    zone = listing.resolve(data, "build_zone_id", "build_zones")
    shape.req_id(data, "build_zone_id")
    permit_type = shape.req_enum(data, "permit_type", calc.PERMIT_TYPES)
    valid_days = shape.opt_int(data, "valid_days", 1, 730, 120)
    max_resubmissions = shape.opt_int(data, "max_resubmissions", 0, 5, 2)
    row = new_row(
        {
            "build_zone_id": zone["id"],
            "permit_type": permit_type,
            "status": "DRAFT",
            "submission_round": 0,
            "max_resubmissions": max_resubmissions,
            "valid_days": valid_days,
            "approved_at": None,
            "expires_at": None,
            "rejection_reason": None,
            "reviewer_user_id": None,
        }
    )
    insert("permit_applications", row)
    return envelope.created(serialize.permit_application(row))


@bp.get("/permit-applications/<permit_id>")
def read_permit(permit_id):
    auth.gate(READ_ROLES)
    row = must_find("permit_applications", permit_id)
    cascades.expire_permit(row)
    return envelope.ok(serialize.permit_application(row))


@bp.get("/permit-applications")
def list_permits():
    auth.gate(READ_ROLES)
    items = ordered(rows("permit_applications"))
    for row in items:
        cascades.expire_permit(row)
    items = listing.apply_filters(
        items,
        (
            listing.fk("build_zone_id", "build_zone_id", "build_zones"),
            listing.enum("permit_type", "permit_type", calc.PERMIT_TYPES),
            listing.enum("status", "status", calc.PERMIT_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.permit_application)


@bp.post("/permit-applications/<permit_id>/submit")
def submit_permit(permit_id):
    auth.gate(("ProgramManager",))
    permit = must_find("permit_applications", permit_id)
    cascades.expire_permit(permit)
    status = permit["status"]
    if status not in ("DRAFT", "REJECTED"):
        raise ApiError(
            "ERR_PERMIT_APPLICATION_STATE_INVALID",
            "only a draft or rejected application can be submitted",
        )
    if status == "REJECTED" and permit["submission_round"] - 1 >= permit["max_resubmissions"]:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED", "the resubmission allowance is exhausted")
    permit["status"] = "SUBMITTED"
    permit["submission_round"] += 1
    permit["rejection_reason"] = None
    bump(permit)
    return envelope.ok(serialize.permit_application(permit))


@bp.post("/permit-applications/<permit_id>/decision")
def decide_permit(permit_id):
    user_id, _role = auth.gate(("PermitOffice",))
    permit = must_find("permit_applications", permit_id)
    data = shape.body()
    decision = shape.req_enum(data, "decision", calc.PERMIT_DECISIONS)
    reason = shape.opt_str(data, "rejection_reason", 1, 240)
    if decision == "REJECT" and reason is None:
        shape.bad("rejection_reason", "is required for a rejection")
    cascades.expire_permit(permit)
    if permit["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_PERMIT_APPLICATION_STATE_INVALID",
            "only a submitted application can be decided",
        )
    permit["reviewer_user_id"] = user_id
    if decision == "APPROVE":
        permit["status"] = "APPROVED"
        permit["approved_at"] = now()
        permit["expires_at"] = add_days(permit["approved_at"], permit["valid_days"])
        permit["rejection_reason"] = None
    else:
        permit["status"] = "REJECTED"
        permit["rejection_reason"] = reason
    bump(permit)
    return envelope.ok(serialize.permit_application(permit))
