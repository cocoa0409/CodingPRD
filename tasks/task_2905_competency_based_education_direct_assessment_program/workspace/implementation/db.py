"""In-memory store plus the server-side logical clock.

The store always boots EMPTY: no entity is ever seeded, preloaded or
hardcoded. Every row is created by a caller through a declared endpoint.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: the logical clock starts at exactly this instant on every boot.
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600

COLLECTIONS = (
    "programs",
    "competencies",
    "blueprints",
    "students",
    "terms",
    "mentors",
    "assignments",
    "evaluators",
    "attempts",
    "scores",
    "cases",
    "sap_reviews",
    "disbursements",
    "transcripts",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_ORIGIN
        self._seq = 0

    # ---- logical clock -------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant

    # ---- identity / ordering ------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso(instant):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    millis = instant.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year, instant.month, instant.day,
        instant.hour, instant.minute, instant.second, millis,
    )


def parse_instant(raw):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_seconds(instant, seconds):
    return instant + timedelta(seconds=float(seconds))


def add_days(instant, days):
    return instant + timedelta(seconds=float(days) * SECONDS_PER_DAY)


def whole_days_between(start, end):
    """Truncated (floored) whole days between two instants."""
    if start is None or end is None:
        return 0
    delta = (end - start).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // SECONDS_PER_DAY)


def whole_days_ceil_zero(start, end):
    return whole_days_between(start, end)


# ---- row helpers -------------------------------------------------------

def new_row(with_common=True):
    row = {"id": new_id(), "_seq": db.next_seq()}
    if with_common:
        stamp = db.now()
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["version"] = 1
    else:
        row["created_at"] = db.now()
    return row


def touch(row):
    """Record a mutation of a row: bump updated_at and version by exactly 1."""
    if row is None:
        return row
    row["updated_at"] = db.now()
    row["version"] = row.get("version", 1) + 1
    return row


def by_created(rows, descending=False):
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    if descending:
        ordered.reverse()
    return ordered


def sort_rows(rows, keys):
    """Sort by a list of (extractor, descending) pairs, then created_at/_seq."""
    ordered = by_created(rows)
    for extractor, descending in reversed(keys):
        ordered = sorted(ordered, key=lambda r: _sortable(extractor(r)),
                         reverse=descending)
    return ordered


class _Low(object):
    def __lt__(self, other):
        return True

    def __gt__(self, other):
        return False

    def __eq__(self, other):
        return isinstance(other, _Low)

    def __le__(self, other):
        return True

    def __ge__(self, other):
        return isinstance(other, _Low)

    def __hash__(self):
        return 0


LOW = _Low()


def _sortable(value):
    if value is None:
        return LOW
    return value
