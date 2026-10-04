"""In-memory data store and the logical clock.

All state lives in plain dicts keyed by id. The store starts empty on every
boot; nothing is seeded. The logical clock starts at 2026-09-01T00:00:00Z and
moves only via POST /licensure/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

db = {
    "candidates": {},
    "jurisdictions": {},
    "supervisors": {},
    "evaluations": {},
    "reports": {},
    "authorizations": {},
    "divisions": {},
    "supplementals": {},
    "certificates": {},
    "ce_entries": {},
    "transmittals": {},
    "disciplinary": {},
}

_clock = {"current": CLOCK_DEFAULT}


def new_id():
    """Bare UUID, no type prefix."""
    return str(uuid.uuid4())


def parse_instant(value):
    """Parse an ISO 8601 instant (accepts trailing Z) into an aware UTC datetime."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    """Serialize an aware UTC datetime; fractional seconds (3 digits) only when nonzero."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += ".%03d" % (dt.microsecond // 1000)
    return base + "Z"


def get_clock_iso():
    return _clock["current"]


def set_clock_iso(value):
    _clock["current"] = value


def clock_datetime():
    return parse_instant(_clock["current"])


def now_iso():
    """Logical-clock instant, ISO 8601 UTC with three fractional digits."""
    dt = clock_datetime()
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def today():
    """Current logical date (time-of-day never participates in deadlines)."""
    return clock_datetime().date()


def stamp_new(rec):
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec):
    """Every accepted mutation bumps version by one and refreshes updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()
