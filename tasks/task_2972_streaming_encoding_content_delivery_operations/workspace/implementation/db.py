"""In-memory store, logical broadcast clock and shared primitives.

Storage is process-local dictionaries only: every start.sh invocation begins with
a completely empty catalogue.  No entity is ever seeded here -- the only value
established at boot is the logical clock's declared default (PRD 2.5).
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?(Z|z|\+00:00|-00:00)?$"
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.titles = {}
        self.assets = {}
        self.qc_reports = {}
        self.ladders = {}
        self.device_profiles = {}
        self.packages = {}
        self.entitlement_rules = {}
        self.windows = {}
        self.vendors = {}
        self.policies = {}
        self.metrics = {}
        self.reservations = {}
        self.jobs = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical instant.  Nothing in this system reads the wall clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns None when the text is not one."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def minutes(n):
    return timedelta(minutes=int(n))


# ---------------------------------------------------------------------------
# Decimal discipline (PRD 2.8): every quantised value is ROUND_HALF_UP.
# ---------------------------------------------------------------------------

D0 = Decimal("0")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value):
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def money(value):
    return q2(value)


# ---------------------------------------------------------------------------
# Row bookkeeping
# ---------------------------------------------------------------------------


def new_row(versioned=True):
    """Common fields (PRD 2.4).  Immutable resources carry id + created_at only."""
    stamp = now()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and increment version, as any direct mutation would."""
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1
    return row


def stamp_only(row):
    """Refresh updated_at without consuming a version (see worklog notes)."""
    if "updated_at" in row:
        row["updated_at"] = now()
    return row


def rows(collection):
    """Insertion-ordered rows; used as the stable tie-break, never the id."""
    return sorted(collection.values(), key=lambda r: r["_seq"])


def sort_rows(items, keys):
    """Sort by (getter, reverse) pairs, always breaking ties on insertion order."""
    out = sorted(items, key=lambda r: r["_seq"])
    for getter, reverse in reversed(list(keys)):
        out.sort(key=getter, reverse=reverse)
    return out


def by_created(items, reverse=False):
    return sort_rows(items, [(lambda r: r["created_at"], reverse)])
