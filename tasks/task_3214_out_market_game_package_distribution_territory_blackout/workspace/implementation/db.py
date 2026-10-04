"""In-memory data store and logical clock.

The store starts empty on every boot. The logical clock defaults to
exactly 2026-09-01T00:00:00Z and never consults wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string. Returns None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (dt.microsecond // 1000) + "Z"


class Clock:
    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self._now

    def now_iso(self):
        return format_iso(self._now)

    def set(self, dt):
        self._now = dt


class DB:
    def __init__(self):
        self.clock = Clock()
        self.rights_grants = {}
        self.seasons = {}
        self.markets = {}
        self.games = {}
        self.week_slates = {}
        self.offers = {}
        self.accounts = {}
        self.student_verifications = {}
        self.venue_licenses = {}
        self.subscriptions = {}
        self.payments = {}
        self.territory_checks = {}
        self.game_entitlements = {}
        self.complaint_cases = {}
        self.entitlement_overrides = {}
        self.multiview_sessions = {}


db = DB()
