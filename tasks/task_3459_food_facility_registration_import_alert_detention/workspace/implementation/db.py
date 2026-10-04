"""In-memory data store and logical clock for the Food Facility Import
Detention API.

All state is process-local module-level dictionaries. The store starts empty
on every boot; no seeding is performed here or anywhere else.
"""
import re
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity stores (id -> dict)
# ---------------------------------------------------------------------------
facilities = {}
importers = {}
laboratories = {}
prior_notices = {}
entries = {}
samples = {}
alerts = {}
petitions = {}
inspections = {}
recalls = {}

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4). Startup default is exactly
# 2026-09-01T00:00:00Z, never the wall clock. The clock moves forward only.
# ---------------------------------------------------------------------------
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Monotonic counters: global creation sequence (stable ordering / tie-breaks)
# and the facility registration-number sequence (FFR-NNNNNN).
_seq = 0
_reg_seq = 0


def now():
    return _clock


def set_clock(value):
    global _clock
    _clock = value


def next_seq():
    global _seq
    _seq += 1
    return _seq


def next_registration_number():
    global _reg_seq
    _reg_seq += 1
    return "FFR-%06d" % _reg_seq


def new_common():
    """Common system-managed fields for a freshly created resource."""
    instant = _clock
    return {
        "id": str(uuid.uuid4()),
        "created_at": instant,
        "updated_at": instant,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity, at=None):
    """Bump version and updated_at on any modification (PRD section 2.5)."""
    entity["version"] += 1
    entity["updated_at"] = at if at is not None else _clock


def sort_key(entity):
    """Creation-timestamp ascending with a total, server-recorded tie-break."""
    return (entity["created_at"], entity["_seq"])


# ---------------------------------------------------------------------------
# Timestamp parsing / formatting
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 datetime into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Canonical rendering of a logical-clock instant."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        if dt.microsecond % 1000 == 0:
            base += ".%03d" % (dt.microsecond // 1000)
        else:
            base += ".%06d" % dt.microsecond
    return base + "Z"


def wall_now_iso():
    """Response-envelope timestamp: wall clock UTC, three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date; None on failure."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
