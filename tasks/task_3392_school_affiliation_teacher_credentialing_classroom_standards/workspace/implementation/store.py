"""In-memory data store, logical clock, id/timestamp helpers, date math.

Storage is purely in-memory (module-level dicts). Nothing is seeded at
startup; every entity is created through the API. A fresh process (per-test
server reboot) therefore starts with a completely empty store and the logical
clock at exactly 2026-09-01T00:00:00Z.
"""

import calendar
import uuid
from datetime import date, datetime, time, timezone

# PRD 3.2: the uncontrolled method name.
METHOD_NAME = "Montessori"

# PRD 2.5: logical clock initial value; the server never uses wall-clock time.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"


class _DB:
    def __init__(self):
        self.catalogs = {}
        self.schools = {}
        self.classrooms = {}
        self.audits = {}
        self.programs = {}
        self.learners = {}
        self.placements = {}
        self.credentials = {}
        self.applications = {}
        self.self_studies = {}
        self.visits = {}
        self.plans = {}
        self.pd_events = {}
        self.ce_entries = {}
        # Global receipt-order counter; tie-breaks same-instant created_at.
        self.seq = 0
        self.clock_now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.clock_raw = CLOCK_START_ISO


db = _DB()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def now_dt():
    return db.clock_now


def now_date():
    return db.clock_now.date()


def set_clock(dt, raw):
    db.clock_now = dt
    db.clock_raw = raw


# ---------------------------------------------------------------------------
# Timestamp formatting / parsing
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(db.clock_now)


def parse_date(s):
    """Parse a strict YYYY-MM-DD date string; return date or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_datetime(s):
    """Parse an ISO 8601 datetime (Z or numeric offset); return aware UTC
    datetime or None. A bare date is accepted as midnight UTC."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(d, months):
    """Calendar month arithmetic on a date; day clamps to month end."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_months_dt(dt, months):
    """Calendar month arithmetic on a datetime, preserving time-of-day."""
    d = add_months(dt.date(), months)
    return datetime.combine(d, dt.timetz())


# ---------------------------------------------------------------------------
# Record lifecycle helpers
# ---------------------------------------------------------------------------

def stamp_new(rec):
    """Initialize common system fields on a freshly created record."""
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()


def stamp_new_lean(rec):
    """ClassroomAudit / CECreditEntry carry only id + created_at (PRD 2.4)."""
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()


def touch(rec):
    """Register a mutation: bump version and updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def active_catalog():
    """Return the single ACTIVE StandardsCatalog record, or None."""
    for c in db.catalogs.values():
        if c["status"] == "ACTIVE":
            return c
    return None
