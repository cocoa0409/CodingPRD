"""Logical clock, identifier minting and timestamp formatting.

PRD 2.11: all time-dependent evaluation runs against a server-held logical
clock.  The clock starts at exactly 2026-09-01T00:00:00Z when the server starts
and never falls back to wall-clock time before it is first set.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": CLOCK_START}


def now():
    """Current logical clock instant (timezone-aware UTC)."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = CLOCK_START


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2/2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def now_iso():
    return fmt(now())


def parse(value):
    """Tolerant ISO 8601 parser -> aware UTC datetime, or None when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def new_id():
    """Server-minted UUID string, no type prefix, no embedded meaning."""
    return str(uuid.uuid4())


_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    tail = "".join(random.choice(_ALPHANUM) for _ in range(16))
    return "req_" + tail


def new_pickup_code():
    return "".join(random.choice(_ALPHANUM) for _ in range(6))


def new_deposit_reference():
    tail = "".join(random.choice(_ALPHANUM) for _ in range(10))
    return "DEP-" + tail
