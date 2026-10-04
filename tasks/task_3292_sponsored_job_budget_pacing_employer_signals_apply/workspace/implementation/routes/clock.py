"""Logical clock control endpoint."""

from flask import Blueprint

import auth
import validations as V
from db import iso, logical_day, parse_iso, store
from response import ok
from services import calc

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin",))
    data = V.body()
    V.require_fields(data, ["current_utc"])
    raw = V.require_string(data, "current_utc")

    from errors import ERR_INVALID_CLOCK_ORDER, ERR_INVALID_REQUEST, fail

    try:
        target = parse_iso(raw)
    except (TypeError, ValueError):
        fail(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 UTC instant.")

    # Tier 7: the requested instant must not precede the current logical clock.
    if target < store.clock:
        fail(ERR_INVALID_CLOCK_ORDER,
             "The requested instant precedes the current logical clock.")

    campaigns_reset, postings_rederived = calc.advance_clock(target)
    return ok({
        "current_utc": iso(store.clock),
        "day_open_date": iso(logical_day(store.clock)),
        "campaigns_reset": campaigns_reset,
        "postings_rederived": postings_rederived,
    })