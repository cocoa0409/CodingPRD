"""Logical clock endpoint: set the clock and run the delivery sweep (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, get_body
from response import success
from util import fmt_dt, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/lab/_clock/set_current_utc")
def set_current_utc():
    authenticate({"PlatformAdmin"})
    body = get_body()
    target = parse_dt(body.get("to_iso8601"))
    if target is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO8601 instant"
        )
    with dbmod.store.lock:
        dbmod.store.clock = target
        # Delivery sweep: SHIPPED -> DELIVERED once the transit window has elapsed.
        for o in dbmod.store.orders.values():
            if o["status"] != "SHIPPED":
                continue
            transit = timedelta(days=D.TRANSIT_DAYS[o["shipping_class"]])
            if target >= o["shipped_at"] + transit:
                o["status"] = "DELIVERED"
                o["delivered_at"] = o["shipped_at"] + transit
                o["version"] += 1
                o["updated_at"] = target
    return success({"current_utc": fmt_dt(target)})
