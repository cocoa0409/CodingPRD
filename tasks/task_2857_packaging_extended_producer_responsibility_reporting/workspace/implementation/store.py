"""In-memory data store and the server's logical UTC clock.

Storage is process-local dictionaries only: no file, no database, no external
persistence.  The store starts completely EMPTY on every boot -- nothing is
seeded, preloaded or hardcoded.  Every entity is created through the declared
API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

COLLECTIONS = (
    "producers",
    "skus",
    "state_programs",
    "reporting_periods",
    "pros",
    "fee_schedules",
    "registrations",
    "memberships",
    "reports",
    "report_lines",
    "engagements",
    "invoices",
)

DB = {name: {} for name in COLLECTIONS}

# PRD 2.4: before any client sets it the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to the host's real time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_STATE = {"clock": INITIAL_CLOCK}
_SEQ = itertools.count(1)


def clock():
    return _STATE["clock"]


def set_clock(value):
    _STATE["clock"] = value


def next_seq():
    return next(_SEQ)


def new_id():
    return str(uuid.uuid4())


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def now_stamp():
    return fmt_instant(wall_now())


def insert(kind, row):
    row["_kind"] = kind
    row["_seq"] = next_seq()
    DB[kind][row["id"]] = row
    return row


def get(kind, rid):
    if not isinstance(rid, str):
        return None
    return DB[kind].get(rid)


def values(kind):
    return list(DB[kind].values())


def delete(kind, rid):
    DB[kind].pop(rid, None)


def by_created(rows):
    """Default ordering everywhere in the service: created_at ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
