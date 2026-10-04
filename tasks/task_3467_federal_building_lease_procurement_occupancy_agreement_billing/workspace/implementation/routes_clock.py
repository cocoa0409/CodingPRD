"""Logical clock endpoint (PRD section 2.4). Mounted OUTSIDE the /leasing
api prefix, at the root: POST /_clock/set_current_utc. GSAAdmin only."""
from flask import Blueprint

from cascade import sweep_clock
from dates import parse_iso_dt
from envelope import success
from errors import ApiError
from middleware import body, require_auth
from store import CLOCK, now_dt, set_clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth(["GSAAdmin"])
    b = body()
    raw = b.get("to_iso8601")
    dt = parse_iso_dt(raw)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO8601 datetime")
    # the clock is monotonic: setting it backwards is rejected
    if dt < now_dt():
        raise ApiError("ERR_INVALID_REQUEST", 400, "The logical clock is monotonic; to_iso8601 is in the past")
    set_clock(raw, dt)
    t_leases, t_oas, t_plans = sweep_clock(dt.date())
    return success({
        "current_utc": CLOCK["raw"],
        "transitioned_lease_ids": t_leases,
        "transitioned_oa_ids": t_oas,
        "transitioned_plan_ids": t_plans,
    })
