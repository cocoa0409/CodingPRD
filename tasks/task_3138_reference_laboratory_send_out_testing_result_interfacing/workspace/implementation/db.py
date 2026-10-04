"""In-memory data store.

Storage is process-local only: plain dicts keyed by id. Nothing is seeded,
preloaded or persisted; every resource is created through the API surface. The
store begins empty on every boot of the process.
"""

import uuid
from datetime import datetime, timedelta, timezone

# The service's only notion of "now". Startup default is exactly 2026-09-01T00:00:00Z
# and the service never falls back to the host machine's wall-clock time.
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Collection name -> factory for the dict that holds it.
COLLECTIONS = (
    "client_laboratories",
    "courier_runs",
    "test_catalog_entries",
    "specimens",
    "send_out_orders",
    "order_test_lines",
    "instrument_runs",
    "interface_builds",
    "result_interface_messages",
    "billing_ledgers",
    "utilization_advisories",
)


class Store:
    """Holds every collection plus the derived logical clock."""

    def __init__(self):
        self._current_utc = CLOCK_START
        for name in COLLECTIONS:
            setattr(self, name, {})

    # -- logical clock ------------------------------------------------------
    @property
    def clock(self):
        return self._current_utc

    @clock.setter
    def clock(self, value):
        self._current_utc = value

    def reset(self):
        """Drop every row and return the clock to its startup default."""
        for name in COLLECTIONS:
            getattr(self, name).clear()
        self._current_utc = CLOCK_START


db = Store()


def now():
    """The service's only notion of the current instant."""
    return db.clock


def set_now(value):
    db.clock = value


# ---------------------------------------------------------------------------
# common resource fields (PRD section 2.4)
# ---------------------------------------------------------------------------

_TERMINALS = None  # terminal-state map lives in rules.py and is injected lazily


def new_id():
    """Server-minted identifier with no type prefix or namespace embedded."""
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC instant; None passes through.

    Whole-second instants render without a fractional part (PRD sections 2.4 and
    2.5 pin bare instants such as `2026-09-01T09:30:00Z`), while sub-second
    instants carry exactly three fractional digits (PRD section 2.4's
    `api_request_timestamp` precision). Idempotent: a value already rendered as
    an ISO string is returned unchanged, because instants are stored sometimes as
    datetimes and sometimes as the already-serialised strings this function
    produced.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO 8601 instant. A naive instant is read as UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
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


def hours_between(start, end):
    """(end - start) expressed in hours."""
    return (end - start).total_seconds() / 3600.0


def stamp_common(row, kind=None):
    """Fill the system-managed id/created_at/updated_at/version quartet.

    updated_at is stamped from the logical clock so that cascade-derived
    instants stay consistent with the clock the service compares against.
    """
    row["id"] = new_id()
    now = iso(db.clock)
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    if kind is not None:
        row["_kind"] = kind
    return row


def touch(row):
    """Refresh updated_at and bump version by one on any mutation."""
    row["updated_at"] = iso(db.clock)
    row["version"] = int(row.get("version", 1)) + 1
    return row


def get(kind, row_id):
    """Resolve a row by id, or None."""
    if row_id is None:
        return None
    return getattr(db, kind).get(row_id)


def put(kind, row):
    getattr(db, kind)[row["id"]] = row
    return row


def remove(kind, row_id):
    getattr(db, kind).pop(row_id, None)


def all_rows(kind):
    return list(getattr(db, kind).values())


def serialize(row):
    """Present a row as JSON: drop internal keys, render instants as ISO 8601."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        else:
            out[key] = value
    return out


def ms_since(dt):
    """Hours as a 2dp decimal number."""
    return round(dt, 2)


def add_hours(dt, hours):
    return dt + timedelta(hours=float(hours))


def add_days(dt, days):
    return dt + timedelta(days=days)