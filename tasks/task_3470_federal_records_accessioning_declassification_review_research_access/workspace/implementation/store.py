"""In-memory state store + the single logical clock.

Storage is plain Python dicts in this module — no SQLite, no files, no /tmp.
Every boot of the process starts with a completely fresh, empty store and the
logical clock at exactly 2026-09-01T00:00:00Z. Nothing here ever reads
wall-clock time.
"""
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 UTC timestamp string into an aware datetime (UTC)."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    t = s.strip()
    if not t:
        raise ValueError("empty timestamp")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        raise ValueError("timestamp must carry a UTC offset")
    return dt.astimezone(timezone.utc)


class _Store:
    def __init__(self):
        # Entity tables: id -> entity dict (insertion ordered).
        self.agencies = {}
        self.schedules = {}
        self.transfers = {}
        self.collections = {}
        self.reviews = {}
        self.referrals = {}
        self.researchers = {}
        self.pulls = {}
        self.repros = {}
        self.foias = {}
        self.restrictions = {}
        # The single logical clock. Never falls back to wall-clock time.
        self._clock = _parse_iso(CLOCK_DEFAULT_ISO)

    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


DB = _Store()


def new_id():
    """Server-minted UUID, no type prefix."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits (common fields)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def tsc(dt):
    """Logical-clock timestamp format: no fractional part when it is zero, so
    stamped fields string-equal the exact ISO instant the clock was set to."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts3(dt)


def parse_dt(s):
    return _parse_iso(s)
