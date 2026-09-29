"""In-memory data store and the logical clock (PRD 2.4, 2.5).

Storage is plain Python dicts keyed by id. Nothing is seeded: the store starts
empty on every boot and every entity is created through the declared API.
"""

import uuid
from datetime import datetime, timedelta, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "properties",
    "room_types",
    "inventory_days",
    "channels",
    "connections",
    "freeze_windows",
    "rate_plans",
    "mappings",
    "allocations",
    "restrictions",
    "promotions",
    "batches",
    "jobs",
    "reservations",
)

DB = {name: {} for name in TABLES}

_STATE = {"clock": CLOCK_EPOCH, "seq": 0}


def reset():
    for name in TABLES:
        DB[name] = {}
    _STATE["clock"] = CLOCK_EPOCH
    _STATE["seq"] = 0


# --- logical clock -------------------------------------------------------

def now():
    """Current logical-clock instant (timezone aware, UTC)."""
    return _STATE["clock"]


def set_clock(instant):
    _STATE["clock"] = instant


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(now())


def clock_date():
    """Calendar date part of the logical clock, in UTC, as a date object."""
    return now().astimezone(timezone.utc).date()


# --- identity / sequencing ----------------------------------------------

def new_id():
    return str(uuid.uuid4())


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def base_record(with_version=True):
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def bump(rec):
    """Version bump: version += 1 and updated_at refreshed (PRD 2.4)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()
    return rec


def ordered(rows):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def add_days(d, n):
    return d + timedelta(days=n)
