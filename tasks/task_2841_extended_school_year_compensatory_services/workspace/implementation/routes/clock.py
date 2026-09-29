"""The logical-clock control endpoint (PRD sections 2.5 and 4)."""
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint

from auth import ALL_ROLES, endpoint
from envelope import ok
from store import db
from validate import bad, body, req_str

bp = Blueprint("clock", __name__)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d{1,9})?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_instant(value, key="current_utc"):
    match = _INSTANT_RE.match(value.strip())
    if not match:
        raise bad("%s must be an ISO 8601 instant." % key)
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    second = int(match.group(6) or 0)
    frac = match.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = match.group(8)
    try:
        stamp = datetime(year, month, day, hour, minute, second, micro,
                         tzinfo=timezone.utc)
    except ValueError:
        raise bad("%s must be a valid instant." % key)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        delta = timedelta(minutes=int(digits[:2]) * 60 + int(digits[2:4]))
        stamp = stamp - sign * delta
    return stamp


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc():
    data = body()
    raw = req_str(data, "current_utc", 1, None)
    db.clock = parse_instant(raw)
    return ok({})
