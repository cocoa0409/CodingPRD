"""In-memory data store, logical clock and common-field bookkeeping.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every record is created through the declared API surface.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO-8601 instant into a UTC-aware datetime, or return None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def format_instant(dt):
    """Render a datetime as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def whole_minutes_between(start, end):
    """Floored whole minutes from start to end (negative if end precedes start)."""
    seconds = (end - start).total_seconds()
    return int(seconds // 60)


def whole_days_between(start, end):
    """Floored whole days from start to end."""
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)


def new_id():
    return str(uuid.uuid4())


class Store(object):
    """Every collection plus the server-owned logical clock."""

    def __init__(self):
        self.developers = {}
        self.api_products = {}
        self.api_versions = {}
        self.access_applications = {}
        self.quota_assignments = {}
        self.upgrade_requests = {}
        self.usage_windows = {}
        self.sandbox_leases = {}
        self.violation_cases = {}
        self.support_cases = {}
        self.feedback_items = {}
        # support-case communications are internal bookkeeping, not a resource
        self.communications = {}
        self.clock = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
        self._sequence = 0

    # ------------------------------------------------------------------ clock
    def now(self):
        return self.clock

    def next_sequence(self):
        self._sequence += 1
        return self._sequence

    # ------------------------------------------------ common-field management
    def stamp_new(self, record, versioned=True):
        now = self.now()
        record["created_at"] = now
        if versioned:
            record["updated_at"] = now
            record["version"] = 1
        record["_seq"] = self.next_sequence()
        return record

    def touch(self, record):
        """Refresh updated_at and increment the revision counter."""
        record["updated_at"] = self.now()
        record["version"] = record.get("version", 1) + 1
        return record

    # ------------------------------------------------------------- ordering
    def ordered(self, collection, key=None):
        """Default ordering is by creation instant, ties broken by arrival."""
        records = list(collection.values())
        if key is None:
            records.sort(key=lambda r: (r["created_at"], r["_seq"]))
        else:
            records.sort(key=key)
        return records


store = Store()


def reset_store():
    """Only ever used by a fresh process; state never survives a reboot."""
    global store
    store = Store()
    return store
