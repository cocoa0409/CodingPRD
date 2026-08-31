"""In-memory data store, logical clock and common-field helpers.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here; every entity is built by the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_DEFAULT}
_seq = {"n": 0}

# --- collections (all empty at boot) ---------------------------------------
land_managers = {}
volunteers = {}
segments = {}
agreements = {}
plans = {}
reports = {}
permits = {}
parties = {}
shifts = {}
orders = {}
incidents = {}

ALL_COLLECTIONS = [
    land_managers, volunteers, segments, agreements, plans,
    reports, permits, parties, shifts, orders, incidents,
]


# --- clock ------------------------------------------------------------------
def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def now_iso():
    return iso(_clock["now"])


def clock_date():
    return _clock["now"].date()


# --- formatting -------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 UTC datetime.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(d):
    return None if d is None else d.strftime("%Y-%m-%d")


def valid_mmdd(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != "-":
        return False
    try:
        datetime.strptime("2000-" + value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# --- entity helpers ---------------------------------------------------------
def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_entity(fields):
    """Create an entity dict carrying the four common properties."""
    stamp = now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = next_seq()
    row["_created_dt"] = now()
    return row


def touch(row):
    """Refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """Sibling rows in created_at ascending order (stable by insertion)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def created_dt(row):
    return row.get("_created_dt")


def hours_between(a, b):
    return (b - a) / timedelta(hours=1)
