"""POST /wish-grant/_clock/set_current_utc — logical clock + offer expiry sweep."""

from flask import Blueprint

from auth import require_roles
from db import STORE, now, set_clock, touch
from resp import ok
from util import body_json, req_field, parse_datetime, iso3

bp = Blueprint("clock", __name__)


@bp.post("/wish-grant/_clock/set_current_utc")
@require_roles("NationalAdmin")
def set_current_utc():
    body = body_json()
    dt = parse_datetime(req_field(body, "to_iso8601"), "to_iso8601")
    set_clock(dt)
    today = now().date()
    for o in STORE["offers"].values():
        if (
            o["status"] == "AVAILABLE"
            and o["quantity_reserved"] == 0
            and o["valid_until"] < today
        ):
            o["status"] = "EXPIRED"
            touch(o)
    return ok({"current_utc": iso3(now())})
