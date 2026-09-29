"""Response envelope helpers (PRD section 2.2) and the logical clock (PRD 2.4)."""

import random
import string
import threading
from datetime import datetime, timedelta, timezone

from flask import jsonify

# --------------------------------------------------------------------------
# Logical clock.  Reads exactly 2026-08-01T00:00:00Z until a
# ProgramAdministrator repositions it; it never falls back to wall time.
# --------------------------------------------------------------------------
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock_lock = threading.RLock()
_clock_value = INITIAL_CLOCK


def clock_now():
    with _clock_lock:
        return _clock_value


def clock_set(value):
    global _clock_value
    with _clock_lock:
        _clock_value = value
        return _clock_value


def clock_reset():
    global _clock_value
    with _clock_lock:
        _clock_value = INITIAL_CLOCK


# --------------------------------------------------------------------------
# ISO 8601 UTC with exactly three fractional digits.
# --------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    """Exact day arithmetic: `days` periods of 86400 seconds, no calendar work."""
    return dt + timedelta(seconds=86400 * int(days))


_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit=None, offset=None, total=None, status=200, paginated=True):
    if total is None:
        total = len(rows)
    pagination = None
    if paginated:
        pagination = {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset or 0) + len(rows) < total,
        }
    body = {"meta": _meta(pagination), "response_type": "array", "data": rows}
    return jsonify(body), status


def created_list(rows):
    return ok_list(rows, status=201, paginated=False)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
