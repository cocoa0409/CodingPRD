"""In-memory store, logical clock and shared time helpers.

Storage is purely in-memory: plain Python dicts keyed by the server-minted
UUID of each row.  Nothing is persisted to disk and NOTHING is seeded at
import time or at boot -- every collection below starts empty on every fresh
process, exactly as PRD section 2.11 and the harness's per-test reboot require.
"""

import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

# PRD 2.11: "Before any caller sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z, and it must not fall back to the host's own time under
# any circumstance."
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class Store:
    """Every collection in the system, plus the logical clock."""

    def __init__(self):
        self.patients = {}
        self.clinicians = {}
        self.drugs = {}
        self.payer_plans = {}
        self.chairs = {}
        self.visits = {}
        self.screening_records = {}
        self.episodes = {}
        self.authorizations = {}
        self.monitoring_labs = {}
        self.appointments = {}
        self.enrollments = {}
        self.clock = LOGICAL_CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        """The logical clock.  Never the host wall clock."""
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(value):
    """ISO 8601 UTC instant with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(text):
    """Parse an ISO 8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def parse_date_only(text):
    """Parse a calendar date with no time component (PRD 3.1)."""
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def add_days(instant, days):
    return instant + timedelta(days=days)


def add_minutes(instant, minutes):
    return instant + timedelta(minutes=minutes)


def elapsed_whole_days(later, earlier):
    """PRD 2.7: elapsed-time quantities are whole units and truncate.

    Whole days obtained by dividing the elapsed time by one day and
    discarding any remainder (floor division, so it also truncates
    consistently for a future instant).
    """
    seconds = (later - earlier).total_seconds()
    return int(seconds // 86400)


def elapsed_whole_weeks(later, earlier):
    """PRD 2.7: whole weeks obtained by dividing elapsed time by seven days."""
    seconds = (later - earlier).total_seconds()
    return int(seconds // (7 * 86400))


def sort_rows(rows):
    """PRD 2.3: list results are always ordered by created_at ascending.

    Ties (very common because created_at is stamped from the logical clock)
    are broken by insertion order so paging is stable.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def stamp_new(row):
    """Attach identity + creation stamps from the logical clock."""
    now = db.now()
    row["id"] = new_id()
    row["created_at"] = now
    row["_seq"] = db.next_seq()
    return row


def stamp_versioned(row):
    """Most resources also carry updated_at and version (PRD 2.4)."""
    stamp_new(row)
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at without advancing version (PRD 2.4 / 2.9)."""
    if "updated_at" in row:
        row["updated_at"] = db.now()
    return row


def bump(row):
    """Refresh updated_at and advance version by exactly one."""
    if "updated_at" in row:
        row["updated_at"] = db.now()
    if "version" in row:
        row["version"] += 1
    return row


def dec(value):
    """A Decimal view of a JSON number without float contamination."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
