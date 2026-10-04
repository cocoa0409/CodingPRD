"""In-memory data store, logical clock, and record helpers (PRD sections 2.4, 2.5).

Storage is plain Python dicts; the store starts empty on every boot and nothing
is seeded. The logical clock defaults to exactly 2026-09-01T00:00:00Z and never
falls back to wall-clock time.
"""
import itertools
import uuid
from datetime import datetime, timezone

DB = {
    "districts": {},
    "contracts": {},
    "water_years": {},
    "observations": {},
    "announcements": {},
    "allocation_lines": {},
    "reservoirs": {},
    "release_orders": {},
    "constraints": {},
    "incidents": {},
    "delivery_orders": {},
    "revenue_periods": {},
    "transfers": {},
    "impact_reviews": {},
    "agreements": {},
}

_seq_counter = itertools.count(1)

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 timestamp string to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def wallclock_iso():
    """Wall-clock timestamp for the response meta block only."""
    return fmt_dt(datetime.now(timezone.utc))


def new_record():
    """System-managed fields for a fresh mutable record (id/created/updated/version)."""
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD section 2.5)."""
    record["updated_at"] = clock_now()
    record["version"] += 1
