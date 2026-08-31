"""Position restrictions and the logical compliance clock."""
from flask import Blueprint, g

from core import ApiError, db, iso_ms, ok, ok_list, touch
from domain import release_expired_restrictions
from serialize import restriction_out
from validation import (READER_ROLES, body, endpoint, must_exist, paginate,
                        pagination, query_enum, query_str, req_instant, req_str)

bp = Blueprint("misc", __name__)

RESTRICTION_STATUSES = ("RESTRICTED", "WAIVED", "RELEASED")


@bp.route("/position-restrictions/<restriction_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_restriction(restriction_id):
    release_expired_restrictions()
    record = must_exist("restrictions", restriction_id)
    return ok(restriction_out(record))


@bp.route("/position-restrictions", methods=["GET"])
@endpoint(READER_ROLES)
def list_restrictions():
    limit, offset = pagination()
    employee_id = query_str("employee_id")
    site_id = query_str("site_id")
    job_title = query_str("job_title")
    status = query_enum("restriction_status", RESTRICTION_STATUSES)
    release_expired_restrictions()

    rows = sorted(db.restrictions.values(), key=lambda r: r["_seq"])
    if employee_id is not None:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if job_title is not None:
        rows = [r for r in rows if r["job_title"] == job_title]
    if status is not None:
        rows = [r for r in rows if r["restriction_status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list([restriction_out(r) for r in page], limit, offset, total)


@bp.route("/position-restrictions/<restriction_id>/waive", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def waive_restriction(restriction_id):
    payload = body()
    reason = req_str(payload, "waiver_reason")
    record = must_exist("restrictions", restriction_id)
    if record["restriction_status"] != "RESTRICTED":
        raise ApiError("ERR_INVALID_RESTRICTION_STATE", 409)
    record["restriction_status"] = "WAIVED"
    record["waiver_reason"] = reason
    record["waived_by_user_id"] = g.user_id
    touch(record)
    return ok(restriction_out(record))


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["SystemAdmin"])
def set_clock():
    payload = body()
    instant = req_instant(payload, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": iso_ms(db.clock)})
