"""The single logical clock every temporal rule reads (§2.10) and the envelope.

The clock's startup default is exactly 2026-09-01T00:00:00Z and it never falls
back to wall-clock time before it is explicitly set.
"""

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_lock = threading.RLock()
_clock = DEFAULT_CLOCK.replace()


def get_clock():
    """The current logical instant, always UTC."""
    with _lock:
        return _clock.replace()


def set_clock(dt):
    """Point the logical clock at `dt`."""
    global _clock
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    with _lock:
        _clock = dt.astimezone(timezone.utc)


def advance_clock(minutes):
    """Advance the logical clock by a whole number of minutes."""
    with _lock:
        set_clock(_clock + timedelta(minutes=minutes))
        return _clock.replace()


def iso(dt):
    """The canonical serialized instant.

    A whole-second instant is written compactly as `2026-09-01T00:00:00Z`; a
    sub-second instant keeps exactly three fractional digits. Zulu instants all
    end in `Z` regardless of whether the microsecond component is zero. Values
    already stored in wire form pass through unchanged.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = _as_utc(dt)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso(dt=None):
    """ISO 8601 UTC, compact for whole seconds and three fractional digits otherwise."""
    return iso(dt or get_clock())


def _as_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(value, field="value"):
    """Parse a client-supplied instant into an aware UTC datetime."""
    from errors import ApiError, ERR_INVALID_REQUEST

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 timestamp.")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 timestamp.")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# Monotonic counter backing the creation-order tie-breaks the selectors use.
# created_at alone cannot separate two rows minted inside the same microsecond.
_seq_lock = threading.RLock()
_seq = [0]


def next_seq():
    with _seq_lock:
        _seq[0] += 1
        return _seq[0]


def new_id():
    """System-minted identifier: a bare UUID, no type prefix (§2.5)."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex.upper()[:16]


READ_ONLY_METHODS = ("GET", "HEAD", "OPTIONS")


def make_meta(request_id=None, limit=None, offset=None, total_count=None, has_more=None):
    """The `meta` object of an envelope.

    A read has no logical instant of its own, so its timestamp reports the current
    logical clock — which is what lets a caller correlate a read with the temporal
    rules it evaluates. A write is stamped with the instant that actually completed it.
    """
    from flask import request as _request

    if _request and _request.method in READ_ONLY_METHODS:
        stamp = now_iso()
    else:
        stamp = now_iso(datetime.now(timezone.utc))
    meta = {
        "api_request_id": request_id or new_request_id(),
        "api_request_timestamp": stamp,
    }
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = has_more
    return meta


def ok(data, request_id=None, status=200, limit=None, offset=None,
       total_count=None, has_more=None):
    """Success envelope: meta + response_type + data (§2.2)."""
    from flask import jsonify

    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": make_meta(request_id, limit, offset, total_count, has_more),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def debug_enabled():
    return os.environ.get("IMPL_DEBUG") == "1"