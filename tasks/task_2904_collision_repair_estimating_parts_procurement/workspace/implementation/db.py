"""In-memory store and the logical clock (PRD 2.4).

The store starts completely empty on every boot: no entity is ever seeded.
"""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# Before the clock has been set for the first time it reads exactly 2026-08-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "customers",
    "insurers",
    "parts_vendors",
    "stalls",
    "calibration_bays",
    "repair_orders",
    "damage_lines",
    "estimate_lines",
    "supplements",
    "parts_lines",
    "procedure_records",
    "stage_assignments",
    "parts_delay_events",
    "qc_inspections",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def now():
    """Current logical clock instant."""
    return store.clock


def set_clock(dt):
    store.clock = dt.astimezone(timezone.utc)
    return store.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return iso(store.clock)


def wall_iso():
    dt = datetime.now(timezone.utc)
    return iso(dt)


def parse_iso(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime, or None if unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # An ISO-8601 *instant* carries the 'T' date/time designator. A bare calendar
    # date, or a space-separated "2026-08-01 08:00" form, names no instant at all
    # and must not parse (PRD 2.5 rung 8, PRD 3.3 and PRD 3.8).
    if "T" not in text and "t" not in text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_days(dt, days):
    """A day is 86400 seconds, with no calendar or leap adjustment (PRD 3.9)."""
    return dt + timedelta(seconds=86400 * days)


def floor_minutes(start, end):
    """Whole minutes, floored, between two instants."""
    delta = (end - start).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // 60)


def base_row(row_id=None, mutable=True):
    """Common system fields (PRD 2.4)."""
    row = {
        "id": row_id or new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
    if mutable:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """A mutation of the row: refresh updated_at and increment version."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def in_creation_order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
