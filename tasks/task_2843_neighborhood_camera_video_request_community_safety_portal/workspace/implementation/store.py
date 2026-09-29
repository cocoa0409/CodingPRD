"""In-memory data store, logical clock and timestamp helpers.

PRD 2.5: the portal never reads real wall-clock time.  Before the clock has
ever been set it reads exactly 2026-08-01T00:00:00Z.

The store starts completely empty on every boot -- nothing is seeded.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.agencies = {}
        self.officers = {}
        self.residents = {}
        self.devices = {}
        self.request_areas = {}
        self.video_requests = {}
        self.solicitations = {}
        self.clips = {}
        self.posts = {}
        self.cases = {}
        self.reports = {}
        self.dispatches = {}
        self.data_control_actions = {}
        # area_id -> ordered list of {"device_id": .., "distance_sq": ..}
        self.rosters = {}
        self.clock = CLOCK_EPOCH


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    m = _ISO_RE.match(s)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzpart = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    """Whole-day offset preserving the time of day to the second (PRD 3.6)."""
    return dt + timedelta(days=days)


def utc_date(dt):
    dt = dt.astimezone(timezone.utc)
    return (dt.year, dt.month, dt.day)


def by_created(rows):
    """Stable ascending created_at ordering (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: r["created_at"])
