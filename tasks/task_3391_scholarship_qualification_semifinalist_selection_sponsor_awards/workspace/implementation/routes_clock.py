"""Logical clock endpoint (PRD 2.5): monotonic advance, offer-expiry sweep,
cycle-completion re-evaluation. Never releases notifications or
disbursements."""

from flask import Blueprint

import constants as C
import services
from errors import err
from helpers import bad, body, require_present, require_roles, resp_object
from store import clock_now, iso_z, parse_dt, set_clock

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def set_current_utc():
    b = body()
    require_present(b, "to_iso8601")
    try:
        target = parse_dt(b["to_iso8601"])
    except (ValueError, AttributeError, TypeError):
        bad("to_iso8601 must be an ISO 8601 datetime")
    # Priority 8: the clock is monotonic; strictly increasing only.
    if target <= clock_now():
        err("ERR_CLOCK_REGRESSION", "logical clock may only move forward")
    set_clock(target)
    expired_ids = services.sweep_expired_offers(target)
    services.check_all_cycles()
    return resp_object({"current_utc": iso_z(target), "expired_offer_ids": expired_ids})
