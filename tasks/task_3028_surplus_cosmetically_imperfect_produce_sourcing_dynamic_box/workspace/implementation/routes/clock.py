"""The test-driving clock endpoint (§2.4)."""

from flask import Blueprint

import clock
import envelope
import params
import store
from common import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    from routes import helpers

    actor = helpers.actor()
    helpers.admin(actor)
    payload = params.body()
    params.missing(payload, ["to_iso8601"])
    try:
        instant = clock.parse_instant(payload["to_iso8601"])
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 must be an ISO 8601 instant.")
    clock.set_now(instant)
    from services import orders, subscriptions

    subscriptions.tick_clock()
    for order in store.BOX_ORDERS.values():
        orders.tick(order)
    return envelope.object_response({"current_utc": clock.format_instant(instant)})