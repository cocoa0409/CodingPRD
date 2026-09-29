"""In-memory store, the logical clock, and identity / timestamp helpers.

PRD 2.4: "Time in this system is entirely logical. The server holds a logical
clock that reads exactly 2026-08-01T00:00:00Z before any call is made, and it
never falls back to wall-clock time."

Everything below lives in ordinary Python dicts: the process holds all state and
a fresh boot starts completely empty.  No entity is ever seeded.
"""

import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_lock = threading.RLock()


class Store:
    def __init__(self):
        self.studios = {}
        self.publishers = {}
        self.publisher_users = {}
        self.agreements = {}
        self.milestones = {}
        self.builds = {}
        self.reviews = {}
        self.payments = {}
        self.change_orders = {}
        self.engagements = {}
        self.invoices = {}
        self.statements = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
lock = _lock


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def now():
    return db.clock


def set_clock(value):
    db.clock = value


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    aware = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        aware.year, aware.month, aware.day,
        aware.hour, aware.minute, aware.second,
        aware.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(db.clock)


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(text):
    """Parse an ISO 8601 instant. Returns None when malformed."""
    if not isinstance(text, str):
        return None
    match = _INSTANT_RE.match(text.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    micro = 0
    if fraction:
        digits = (fraction[1:] + "000000")[:6]
        micro = int(digits)
    try:
        if offset in ("Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if offset[0] == "+" else -1
            off_hours = int(offset[1:3])
            off_minutes = int(offset[4:6])
            tz = timezone(sign * timedelta(hours=off_hours, minutes=off_minutes))
        parsed = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=tz,
        )
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def parse_date(text):
    """Parse a plain ISO 8601 calendar date (YYYY-MM-DD). None when malformed."""
    if not isinstance(text, str):
        return None
    match = _DATE_RE.match(text.strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def shift_date(value, days):
    """Whole calendar day arithmetic on a plain date (PRD 2.4)."""
    return value + timedelta(days=days)


def date_diff_days(later, earlier):
    return (later - earlier).days


def stamp_new(row):
    """Attach the common created_at / updated_at / version quartet."""
    instant = now_iso()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and increment version on a mutated row (PRD 2.8)."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (PRD 2.3), insertion-stable."""
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))
