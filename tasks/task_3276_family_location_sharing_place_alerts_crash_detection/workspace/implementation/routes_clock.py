"""Test-driving endpoints: logical clock and sweeps."""
from flask import Blueprint, request
from db import db, parse_dt, iso
from errors import err_invalid_request
from middleware import get_actor, require_roles
from response import success
from sweeps import run_all_sweeps
from fix_service import check_trip_timeouts

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    actor = get_actor()
    require_roles(actor, {"System"})
    body = request.get_json(silent=True) or {}
    target = parse_dt(body.get("current_utc"))
    if target is None:
        raise err_invalid_request("current_utc must be an ISO-8601 datetime")
    db.clock = target
    check_trip_timeouts()
    summary = run_all_sweeps()
    return success({"current_utc": iso(db.clock)})


@bp.route("/api/_sweeps/age-and-retention", methods=["POST"])
def run_sweeps():
    actor = get_actor()
    require_roles(actor, {"System"})
    check_trip_timeouts()
    summary = run_all_sweeps()
    return success({
        "promoted_member_ids": summary["promoted_member_ids"],
        "expired_consent_member_ids": summary["expired_consent_member_ids"],
        "retired_fix_count": summary["retired_fix_count"],
    })
