"""In-memory data store and logical clock.

The store starts empty on every boot; no seeding. All entities are plain
dicts keyed by id. A monotonic sequence number (`_seq`) gives a stable
insertion order used as the final deterministic tie-break where the PRD
pins submitted_at (which can tie under a frozen logical clock).
"""
import itertools
import uuid
from datetime import datetime, timezone

# Logical clock startup default: exactly 2026-09-01T00:00:00Z (PRD 2.5).
_CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.series = {}
        self.positions = {}
        self.announcements = {}
        self.applicants = {}
        self.documents = {}
        self.applications = {}
        self.assessments = {}
        self.certificates = {}
        self.entries = {}
        self.pass_overs = {}
        self.offers = {}
        self.suitability = {}
        self.clearances = {}
        self.appeals = {}
        self.appointments = {}
        self.clock = _CLOCK_DEFAULT
        self.seq = itertools.count(1)


DB = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return DB.clock


def set_clock(dt):
    DB.clock = dt


def next_seq():
    return next(DB.seq)


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits
    (PRD 2.2/2.4: api_request_timestamp, created_at, updated_at)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock_dt(dt):
    """Serialize a clock-sourced or computed timestamp as the logical clock
    itself renders (PRD 2.5: "the clock reads exactly 2026-09-01T00:00:00Z"):
    no fractional part at whole-second instants, three fractional digits
    otherwise (PRD 2.10: timestamps are carried without rounding)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4)."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1


def base_fields():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
