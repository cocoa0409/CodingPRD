"""In-memory data store, logical park clock and row bookkeeping.

The store starts EMPTY on every boot; no entity is ever seeded, preloaded or
hardcoded here. Every row is created through a declared endpoint.
"""

import re
import uuid
from datetime import datetime, date, timedelta, timezone

UTC = timezone.utc

# The logical clock reads exactly this instant at process start (PRD 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "attractions",
    "components",
    "templates",
    "checklist_items",
    "inspections",
    "item_results",
    "bulletins",
    "bulletin_actions",
    "downtime_events",
    "requisitions",
    "certifications",
    "incidents",
    "shop_bays",
    "work_orders",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

def now():
    """Current logical clock instant. Never reads the wall clock."""
    return db.clock


def now_iso():
    return iso(db.clock)


def today():
    """The logical clock's current UTC calendar date."""
    return db.clock.date()


def today_str():
    return db.clock.date().isoformat()


def set_clock(dt):
    db.clock = dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# instant / date formatting and parsing
# ---------------------------------------------------------------------------

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 UTC instant; return None when malformed."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(8) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        base = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    off = m.group(9)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        try:
            hours = int(digits[:2])
            minutes = int(digits[2:4])
        except ValueError:
            return None
        base = base - sign * timedelta(hours=hours, minutes=minutes)
    return base


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date; return None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def instant_of(row_value):
    """Parse a stored instant string (always well formed)."""
    return parse_instant(row_value) if row_value else None


def date_of(row_value):
    return parse_date(row_value) if row_value else None


# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------

def new_row(versioned=True, **fields):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = now_iso()
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Register a genuine mutation of this row (PRD 2.5 / 2.11)."""
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1


def rows(collection):
    return list(getattr(db, collection).values())


def by_seq(items):
    return sorted(items, key=lambda r: r["_seq"])


def order_by(items, *keys):
    """Stable ordering; the insertion sequence is always the final tie-break."""
    def sort_key(row):
        out = []
        for k in keys:
            v = row.get(k)
            out.append((v is None, v if v is not None else ""))
        out.append((False, row["_seq"]))
        return out
    return sorted(items, key=sort_key)


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


def create(collection, versioned=True, **fields):
    return insert(collection, new_row(versioned=versioned, **fields))
