"""The logical service clock (PRD 2.5)."""

import datetime as _dt

from flask import Blueprint

import calc
import store
from envelope import ok
from errors import ApiError
from guards import ALL_ROLES, authorize, body, validate_body

bp = Blueprint("clock", __name__)

CLOCK_SPEC = [{"name": "to_iso8601", "kind": "string", "min_len": 1}]


def _parse_instant(raw):
    text = raw.strip()
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = _dt.datetime.combine(_dt.date.fromisoformat(text), _dt.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(ALL_ROLES)
    data = validate_body(body(), CLOCK_SPEC)
    instant = _parse_instant(data["to_iso8601"])
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'to_iso8601' must be an ISO 8601 instant.")
    store.set_clock(instant, data["to_iso8601"])
    for driver in store.drivers.values():
        calc.recompute_driver_duty(driver, bump=False)
    return ok({"current_utc": data["to_iso8601"],
               "current_service_date": store.clock_service_date()})
