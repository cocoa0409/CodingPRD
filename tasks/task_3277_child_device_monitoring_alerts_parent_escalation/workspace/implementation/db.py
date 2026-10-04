"""In-memory data store and logical clock."""
import threading
from datetime import datetime, timezone, timedelta


class Clock:
    """Logical clock. Starts at 2026-09-01T00:00:00Z; never falls back to wall clock."""

    DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self._now = self.DEFAULT
        self._lock = threading.Lock()

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt


def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime. Returns None on failure."""
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


def fmt_iso(dt):
    """Format an aware UTC datetime as ISO8601 with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


class Store:
    """All entity collections. Starts empty; entities only appear via API calls."""

    def __init__(self):
        self.families = {}          # id -> FamilyAccount dict
        self.parents = {}           # id -> ParentMember dict
        self.children = {}          # id -> ChildProfile dict
        self.devices = {}           # id -> Device dict
        self.connections = {}       # id -> ServiceConnection dict
        self.content_items = {}     # id -> ContentItem dict
        self.alerts = {}            # id -> Alert dict
        self.escalation_cases = {}  # id -> EscalationCase dict
        self.screen_time_windows = {}  # id -> ScreenTimeWindow dict
        self.filter_rules = {}      # id -> FilterRule dict
        self.bypass_events = {}     # id -> BypassEvent dict
        self.access_grants = {}     # id -> DeviceAccessGrant dict
        self.districts = {}         # id -> District dict
        self.district_links = {}    # id -> DistrictLink dict
        self.lock = threading.RLock()


clock = Clock()
store = Store()
