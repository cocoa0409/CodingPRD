"""In-memory data store, logical clock and datetime helpers.

Storage is process-local Python dicts keyed by id. Nothing is persisted to
disk and NO entity data is ever seeded at startup: every row is created by
callers through the declared API surface.
"""
import datetime
import itertools
import random
import re
import string
import uuid

UTC = datetime.timezone.utc

# PRD 2.5: before the clock is ever set explicitly it reads exactly this
# instant. The service never falls back to wall-clock time for domain rules.
DEFAULT_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:[.,](\d{1,9}))?(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime.datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = datetime.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * delta
    return base


def fmt_iso(dt):
    """Canonical ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.datetime.now(tz=UTC)


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


class Store(object):
    """All collections live here; keyed by row id."""

    COLLECTIONS = (
        "providers", "certificates", "plans", "customers", "assignments",
        "attestations", "observations", "tracebacks", "notices",
        "blocking_events", "disputes", "enforcements", "reports",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        """The current logical compliance clock (PRD 2.5)."""
        return self.clock

    def set_clock(self, dt):
        self.clock = dt.astimezone(UTC)


db = Store()


def base_row(versioned=True):
    """id / created_at (+ updated_at / version) common fields (PRD 2.4)."""
    stamp = wall_now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": db.next_seq(),
        "_raw": {},
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4)."""
    if "version" in row:
        row["updated_at"] = wall_now()
        row["version"] = row["version"] + 1


def order_rows(rows):
    """Default ordering: created_at ascending (PRD 2.3), stable by insertion."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def remember_raw(row, field, raw):
    """Echo client-supplied datetime strings back verbatim."""
    if raw is not None:
        row["_raw"][field] = raw


def serialize(row, fields):
    out = {}
    raw = row.get("_raw", {})
    for field in fields:
        value = row.get(field)
        if isinstance(value, datetime.datetime):
            out[field] = raw.get(field) or fmt_iso(value)
        else:
            out[field] = value
    return out
