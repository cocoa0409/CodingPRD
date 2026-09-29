"""Section 2.8 - the logical clock and the two subscription sweeps."""

from flask import Blueprint

import auth
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/erm/_clock/set_current_utc")
def set_current_utc():
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    data = shape.body()
    raw = shape.req_string(data, "to_iso8601")
    target = store.parse_instant(raw)
    if target is None:
        shape.bad("Field 'to_iso8601' must be an ISO 8601 UTC instant.")

    # priority 31 - the logical clock never runs backwards
    if target < store.clock_dt():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")

    store.set_clock(target)
    activated, expired = services.sweep_subscriptions()
    return envelope.object_response({
        "current_utc": store.clock_iso(),
        "activated_subscription_ids": activated,
        "expired_subscription_ids": expired,
    })
