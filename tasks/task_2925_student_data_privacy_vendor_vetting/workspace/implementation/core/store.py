"""In-memory data store, logical clock and common-field bookkeeping.

The store is empty on every boot: no entity is seeded, preloaded or hardcoded.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# collections -- every value is a dict keyed by the row's server-minted id
# ---------------------------------------------------------------------------
vendors = {}
subprocessors = {}
applications = {}
teachers = {}
analysts = {}
requests = {}
reviews = {}
commitments = {}
catalog_entries = {}
detections = {}
incidents = {}

_seq = itertools.count(1)

# PRD 2.4: before the clock has ever been set it reads exactly this instant and
# never falls back to real time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
    return dt


def new_id():
    return str(uuid.uuid4())


def wall_now():
    """Wall-clock UTC, truncated to milliseconds; used for created_at/updated_at."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def new_row(extra=None):
    ts = wall_now()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }
    if extra:
        row.update(extra)
    return row


def bump(row):
    """Unconditional mutation stamp: refresh updated_at and advance version."""
    row["updated_at"] = wall_now()
    row["version"] = row["version"] + 1
    return True


def apply(row, changes, force=False):
    """Write `changes`; stamp updated_at/version only when a value really moved.

    PRD 2.4/2.10: any operation that changes a row refreshes updated_at and
    increments version, including rows touched indirectly by a cascade.
    """
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            changed = True
        row[key] = value
    if changed or force:
        bump(row)
    return changed


def ordered(rows):
    """PRD 2.3: created_at ascending, stable across pages."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)
