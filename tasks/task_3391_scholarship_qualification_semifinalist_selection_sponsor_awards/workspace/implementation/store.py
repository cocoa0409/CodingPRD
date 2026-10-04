"""In-memory data store and logical clock.

Storage is in-memory only: plain dicts keyed by id, initialized empty at
import time. No seeding, no disk persistence. The server is restarted per
test by the harness, so every boot starts from an empty store.

The logical clock is the sole source of "now" for business decisions
(deadlines, embargoes, scheduled dates, sweeps). created_at/updated_at are
wall-clock audit metadata only and never drive business logic.
"""

import uuid
from datetime import datetime, timezone

import constants as C


def _parse_iso(s):
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Entity tables: id -> record (plain dict).
db = {
    "cycles": {},
    "allocations": {},
    "schools": {},
    "students": {},
    "entries": {},
    "applications": {},
    "sponsors": {},
    "agreements": {},
    "colleges": {},
    "awards": {},
    "disbursements": {},
    "renewals": {},
    "notifications": {},
}

# Monotonic creation counter used as a deterministic tie-break after
# created_at (internal only, never serialized).
_seq_counter = [0]

# The logical clock; starts at exactly the PRD-mandated instant.
_clock = {"now": _parse_iso(C.CLOCK_START_ISO)}


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def iso_ts(dt):
    """Audit-timestamp format: ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_z(dt):
    """Logical-instant format: ISO 8601 UTC, seconds precision unless the
    instant carries a fractional part (then three fractional digits)."""
    if dt.microsecond:
        return iso_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    return _parse_iso(value)


def base_record():
    """Common field set: id, created_at, updated_at, version (PRD 2.4)."""
    now = iso_ts(wall_now())
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Every mutation of a versioned resource bumps version by exactly 1."""
    rec["version"] += 1
    rec["updated_at"] = iso_ts(wall_now())
