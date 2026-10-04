"""In-memory store, logical clock, response envelope helpers, and API error type.

Storage is dicts keyed by id, in-memory only. A fresh process boots with empty
state and the logical clock at exactly 2026-09-01T00:00:00Z; nothing is seeded.
"""
import uuid
from datetime import datetime, timezone


class ApiError(Exception):
    """Carries an error_id, HTTP status, and human-readable message."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------
db = {
    "customers": {},
    "evaluations": {},
    "contracts": {},
    "plants": {},
    "networks": {},
    "connections": {},
    "tanks": {},
    "readings": {},
    "deliveries": {},
    "certificates": {},
    "turnarounds": {},
    "statements": {},
}

_seq = [0]


def next_seq():
    """Monotonic creation sequence; final deterministic tie-break."""
    _seq[0] += 1
    return _seq[0]


# ---------------------------------------------------------------------------
# Logical clock (never wall-clock)
# ---------------------------------------------------------------------------
_clock = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Ids, timestamps, envelope
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000)


def now_iso():
    return fmt_ts(clock_now())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def ok(data, response_type="object", status=200, pagination=None):
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}, status


def err_body(error_id, message):
    return {
        "meta": {"api_request_id": new_request_id(),
                 "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------
def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


def base_entity():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def pub(entity):
    """Public view: strip internal keys (those prefixed with '_')."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Datetime parsing (tolerant ISO 8601; naive values are treated as UTC)
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
