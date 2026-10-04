"""Administrative operations -- the logical clock and the reconciliation sweep
(PRD 2.13).

POST /_clock/set_current_utc
POST /_ops/run_sweep
"""
from flask import Blueprint

import cascades
import derived
from auth import guard
from errors import ApiError
from response import ok
from store import db, parse_instant
from validate import body, reject_unknown, req_str

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["current_utc"])
    current_utc = req_str(b, "current_utc")
    parsed = parse_instant(current_utc)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 UTC instant.")
    # Moving the clock fires no automatic transition; only the sweep applies them.
    db.clock = parsed
    return ok({"current_utc": derived.iso_of(parsed)})


@bp.post("/_ops/run_sweep")
def run_sweep():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    work_orders_breached = cascades.sweep_work_orders()
    agreements_expired = cascades.sweep_agreements()
    remediations_escalated = cascades.sweep_remediations()
    return ok({
        "work_orders_breached": work_orders_breached,
        "agreements_expired": agreements_expired,
        "remediations_escalated": remediations_escalated,
    })