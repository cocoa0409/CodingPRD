"""In-memory store, logical clock and instant formatting.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded; every entity is created through the declared API surface.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

UTC = timezone.utc
CLOCK_STARTUP = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.channels = {}
        self.surcharge_rules = {}
        self.partners = {}
        self.fare_filings = {}
        self.ancillaries = {}
        self.bundles = {}
        self.agreements = {}
        self.contracts = {}
        self.offers = {}
        self.offer_items = {}
        self.orders = {}
        self.service_requests = {}
        self.certifications = {}
        self.connectivity_tests = {}
        self.clock = CLOCK_STARTUP
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock. Business decisions never read wall-clock time."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO-8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_INSTANT_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[Tt ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<f>\d+))?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?)?$"
)


def parse_instant(value):
    """Parse a client-supplied ISO-8601 UTC instant. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    m = _INSTANT_RE.match(text)
    if not m:
        raise ValueError("bad instant")
    frac = m.group("f") or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    dt = datetime(
        int(m.group("y")), int(m.group("mo")), int(m.group("d")),
        int(m.group("h") or 0), int(m.group("mi") or 0), int(m.group("s") or 0),
        micro, tzinfo=UTC,
    )
    tz = m.group("tz")
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz_body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz_body[:2]), minutes=int(tz_body[2:4]))
        dt = dt - sign * offset
    return dt


def bump(entity):
    """Refresh updated_at and increment version exactly once per request."""
    from flask import g
    key = id(entity)
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if key in touched:
        return entity
    touched.add(key)
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def common_fields():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def immutable_fields():
    return {"id": new_id(), "created_at": now(), "_seq": db.next_seq()}


def sort_key(entity):
    return (entity["created_at"], entity["_seq"])


def get_or_404(table, key, error_id):
    entity = table.get(key)
    if entity is None:
        raise ApiError(error_id)
    return entity


def find_opt(table, key):
    if not isinstance(key, str):
        return None
    return table.get(key)
