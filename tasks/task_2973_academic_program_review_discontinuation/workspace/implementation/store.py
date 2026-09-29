"""In-memory storage, the server-wide logical clock, and instant helpers.

Every byte of state lives in process memory only. No file, no database, no
cache. A fresh process therefore starts with an empty portfolio and the
mandatory startup clock default of 2026-08-01T00:00:00Z (PRD 2.5).
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext

getcontext().prec = 60

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        self.programs = {}
        self.snapshots = {}
        self.cycles = {}
        self.self_studies = {}
        self.reviewers = {}
        self.visits = {}
        self.reports = {}
        self.decisions = {}
        self.notifications = {}
        self.plans = {}
        self.guarantees = {}
        self.students = {}
        self.appointments = {}
        # (guarantee_id, student_id) -> seats currently held
        self.holdings = {}

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns None when the value is unusable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second or 0), micro, tzinfo=UTC)
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        dt = dt - sign * delta
    return dt


def days(n):
    """A statutory interval: an exact multiple of 24 hours (PRD 2.5)."""
    return timedelta(hours=24 * int(n))


def utc_date(dt):
    return dt.astimezone(UTC).date()


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(versioned=True):
    row = {"id": new_id(), "created_at": now(), "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    return row


def touch(row):
    """One mutation of a row: refresh updated_at and advance version by 1."""
    row["updated_at"] = now()
    row["version"] = row["version"] + 1


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def dec(value):
    """Exact Decimal from any JSON number without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))
