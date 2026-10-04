"""The logical clock endpoint (PRD 2.4).

POST /_clock/set_current_utc advances the clock (never backwards) and sweeps
VERIFIED evidence documents whose valid_until is now before the clock date
into EXPIRED. current_utc echoes the supplied instant.
"""
from datetime import datetime, timezone

from flask import Blueprint

from errors import ApiError
from middleware import require_roles
from response import ok_obj
from state import DB, CLOCK, touch
from validation import body, req_str

bp = Blueprint("clock", __name__)


def _parse_iso(s):
    txt = s.strip()
    candidate = txt[:-1] + "+00:00" if txt.endswith(("Z", "z")) else txt
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock(_uid, _role):
    b = body()
    raw = req_str(b, "to_iso8601")
    dt = _parse_iso(raw)
    if dt < CLOCK["dt"]:
        raise ApiError("ERR_CLOCK_REGRESSION", "the logical clock may not move backwards")
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw.strip()
    date_str = dt.date().isoformat()
    # Expiry sweep: only VERIFIED documents whose validity has lapsed.
    for doc in DB["docs"].values():
        if doc["status"] == "VERIFIED" and doc["valid_until"] < date_str:
            doc["status"] = "EXPIRED"
            touch(doc)
    return ok_obj({"current_utc": CLOCK["raw"]})
