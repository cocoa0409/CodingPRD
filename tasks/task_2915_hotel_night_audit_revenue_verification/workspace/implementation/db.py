"""In-memory data store and logical clock.

The store is empty on every boot. Nothing is seeded, preloaded or hardcoded:
every entity is created by a caller through a declared endpoint.
"""
import itertools
import re
import uuid
from datetime import datetime, timezone

# The logical clock's default reading (PRD 2.5).
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "properties",
    "outlets",
    "periods",
    "business_dates",
    "folios",
    "postings",
    "tickets",
    "batches",
    "ledger_accounts",
    "allowances",
    "documents",
    "card_auths",
    "reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)


store = Store()


def now():
    """Current reading of the logical clock -- the only time source."""
    return store.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO-8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tzs in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tzs[0] == "+" else -1
    body = tzs[1:].replace(":", "")
    offset_minutes = int(body[:2]) * 60 + int(body[2:4])
    from datetime import timedelta
    tz = timezone(sign * timedelta(minutes=offset_minutes))
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date_only(value):
    """Validate a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value):
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value.strip())
    if not m:
        return None
    month = int(m.group(2))
    if month < 1 or month > 12:
        return None
    return int(m.group(1)), month


def insert(collection, row):
    """Stamp identity/audit fields and store the row."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["_seq"] = store.seq()
    if row.get("_kind") != "JournalPosting":
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    getattr(store, collection)[row["id"]] = row
    return row


def ordered(rows):
    """Ascending created_at, insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_of(collection):
    return ordered(list(getattr(store, collection).values()))
