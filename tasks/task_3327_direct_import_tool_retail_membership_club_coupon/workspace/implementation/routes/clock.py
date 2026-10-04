"""Clock admin endpoint."""
from flask import Blueprint, request
from db import DB, fmt_iso, parse_iso
from response import success
from middleware import require_roles
from entities import lazy_membership, lazy_coupon
from errors import raise_err

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("OpsAdmin")
def set_clock():
    body = request.get_json(silent=True) or {}
    dt = parse_iso(body.get("to_iso8601"))
    if dt is None:
        raise_err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 timestamp")
    DB.set_clock(dt)
    # lazy sweeps
    for m in DB.memberships.values():
        lazy_membership(m)
    for c in DB.coupons.values():
        lazy_coupon(c)
    return success({"current_utc": fmt_iso(DB.now())})
