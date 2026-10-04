"""In-memory data store. Empty at boot — no seeding."""
import threading
from datetime import datetime, timezone, timedelta

# Entity collections: id -> dict
developers = {}
apps = {}
versions = {}
scopes = {}          # key: code
scope_requests = {}
review_windows = {}
merchants = {}
installations = {}
consent_records = {}
webhooks = {}
charges = {}
invoices = {}
ledger_entries = {}
samples = {}
strikes = {}
tickets = {}

_counters = {}
_lock = threading.Lock()

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        with _lock:
            return self._now

    def set(self, dt):
        with _lock:
            self._now = dt


clock = LogicalClock()


def parse_dt(s):
    """Parse an ISO-8601 timestamp to an aware datetime in UTC."""
    if isinstance(s, datetime):
        dt = s
    else:
        s2 = str(s).strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def new_uuid():
    import uuid
    return str(uuid.uuid4())


def cycle_of(dt):
    return dt.strftime("%Y-%m")
