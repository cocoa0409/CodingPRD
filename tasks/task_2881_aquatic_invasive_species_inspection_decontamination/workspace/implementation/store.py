"""In-memory data store, the logical program clock, and row bookkeeping.

Every process start begins with a completely empty store; nothing is seeded.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.5 -- before any client sets it the logical clock reads exactly this
# instant, and it never falls back to real wall-clock time.
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        base = base - sign * offset
    return base


def fmt_iso(value):
    """Canonical ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_iso(value)
        if value is None:
            return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.water_bodies = {}
        self.stations = {}
        self.station_hours = {}
        self.inspectors = {}
        self.training_records = {}
        self.watercraft = {}
        self.agreements = {}
        self.records = {}
        self.decon_orders = {}
        self.quarantine_orders = {}
        self.detection_reports = {}
        self.campaigns = {}
        self.clock = LOGICAL_CLOCK_EPOCH


db = Store()


def now():
    """The value of the logical clock at the moment this request is processed."""
    return db.clock


def now_iso():
    return fmt_iso(db.clock)


def new_id():
    return str(uuid.uuid4())


def base_row(with_mutable=True):
    row = {"id": new_id(), "created_at": now_iso()}
    if with_mutable:
        row["updated_at"] = now_iso()
        row["version"] = 1
    return row


def touch(row):
    """Advance a row's version and updated_at, at most once per request."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "_touched_rows", None)
    if touched is None:
        touched = set()
        g._touched_rows = touched
    key = id(row)
    if key in touched:
        return
    touched.add(key)
    row["version"] = row["version"] + 1
    row["updated_at"] = now_iso()


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_created_at(rows):
    """Default listing order: created_at ascending, insertion order breaking ties."""
    return sorted(rows, key=lambda r: r["created_at"])
