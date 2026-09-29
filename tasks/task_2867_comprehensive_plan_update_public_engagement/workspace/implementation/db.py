"""In-memory data store.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: every boot starts with a completely empty store and all
entities are built by callers through the declared endpoints.
"""
import itertools
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from constants import CLOCK_STARTUP_ISO

_COLLECTIONS = [
    "plan_updates",
    "inventory_datasets",
    "growth_scenarios",
    "housing_allocations",
    "plan_elements",
    "consistency_links",
    "venues",
    "engagement_activities",
    "participation_records",
    "environmental_reviews",
    "plan_alternatives",
    "hearings",
    "amendments",
    "implementation_actions",
]


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in _COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_instant(CLOCK_STARTUP_ISO)
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


# --- timestamps -------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(?:[Zz]|[+-]00:?00)$"
)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable.

    PRD 2.4 requires ISO 8601 UTC with three fractional digits. We accept 0-9
    fractional digits and either `Z` or a zero UTC offset; anything else --
    date-only values, naive values and non-UTC offsets -- is malformed.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac = m.groups()
    micros = 0
    if frac:
        micros = int((frac + "000000")[:6])
    try:
        return datetime(int(year), int(month), int(day), int(hour), int(minute),
                        int(second), micros, tzinfo=timezone.utc)
    except ValueError:
        return None


def iso(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def clock_now():
    return db.clock


def add_days(dt, days):
    return dt + timedelta(days=days)


# --- rounding ---------------------------------------------------------------

def round_half_up(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def d1(value):
    """One decimal place, round half up."""
    return round_half_up(value, 1)


def d2(value):
    """Two decimal places, round half up."""
    return round_half_up(value, 2)


def to_num(value):
    """Render a Decimal as a JSON-friendly float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# --- rows -------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_row(fields, versioned=True):
    """Create a row dict with the common identity fields (PRD 2.4)."""
    now = wall_now()
    row = {"id": new_id(), "created_at": now}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = db.next_seq()
    row.update(fields)
    return row


def bump(row):
    """Refresh updated_at and increment version (PRD 2.4)."""
    row["updated_at"] = wall_now()
    row["version"] = row.get("version", 0) + 1
    return row


def sort_rows(rows):
    """List results are always ordered by created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# The single process-local store. Constructed last so the helpers above exist.
db = Store()
