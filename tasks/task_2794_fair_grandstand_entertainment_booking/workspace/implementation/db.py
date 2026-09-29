"""In-memory data store and the logical show clock (PRD sections 2.4, 2.5).

Storage is process-local Python dictionaries keyed by id.  Nothing is persisted
and nothing is ever seeded: every record in this store is created by an API call.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# The logical clock reads exactly this instant at startup (PRD section 2.4).
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

REQUEST_LOCK = threading.RLock()


class Store(object):
    """Every collection in the service, keyed by record id."""

    COLLECTIONS = (
        "editions",
        "stages",
        "agents",
        "artists",
        "offers",
        "offer_rounds",
        "bookings",
        "scales",
        "batches",
        "advances",
        "rider_items",
        "sponsors",
        "activations",
        "settlements",
        "contingency_actions",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# identity and timestamps
# ---------------------------------------------------------------------------

def new_id():
    """Server-minted UUID with no type prefix of any kind (PRD section 2.5)."""
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_ts(text):
    """Parse an ISO 8601 instant that must carry a trailing Z.  None when malformed."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw.endswith("Z") and not raw.endswith("z"):
        return None
    body = raw[:-1]
    fraction = 0
    if "." in body:
        head, frac = body.split(".", 1)
        if not frac.isdigit() or len(frac) == 0:
            return None
        frac = (frac + "000000")[:6]
        fraction = int(frac)
        body = head
    try:
        base = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            base = datetime.strptime(body, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None
    return base.replace(microsecond=fraction, tzinfo=timezone.utc)


def parse_date(text):
    """Parse a strict YYYY-MM-DD calendar date.  None when malformed."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_hhmm(text):
    """Parse an HH:MM time-of-day.  Returns (hour, minute) or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 5 or raw[2] != ":":
        return None
    hh, mm = raw[:2], raw[3:]
    if not (hh.isdigit() and mm.isdigit()):
        return None
    hour, minute = int(hh), int(mm)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return (hour, minute)


def now():
    """The logical clock as a datetime."""
    return db.clock


def now_str():
    """The logical clock rendered in the canonical timestamp format."""
    return fmt_ts(db.clock)


def date_at_time(date_text, hour, minute):
    d = parse_date(date_text)
    if d is None:
        return None
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def day_delta(date_a, date_b):
    """Whole-day difference date_a - date_b for two YYYY-MM-DD strings."""
    a = parse_date(date_a)
    b = parse_date(date_b)
    if a is None or b is None:
        return None
    return (a - b).days


def shift_date(date_text, days):
    d = parse_date(date_text)
    if d is None:
        return None
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# record lifecycle
# ---------------------------------------------------------------------------

def stamp_new(rec, common=True):
    """Attach created_at (and updated_at / version when the type carries them)."""
    rec["created_at"] = now_str()
    if common:
        rec["updated_at"] = now_str()
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def _touched_set():
    if not hasattr(g, "_touched_records"):
        g._touched_records = set()
    return g._touched_records


def touch(rec):
    """Refresh updated_at and increment version, once per record per request.

    PRD section 2.8: every record touched by a cascade hop has its updated_at
    refreshed from the logical clock and its version incremented by one.  A
    single request is a single mutation of any given record, so the bump is
    de-duplicated within the request.
    """
    if rec is None or "version" not in rec:
        return
    seen = _touched_set()
    key = rec.get("id")
    if key in seen:
        return
    seen.add(key)
    rec["updated_at"] = now_str()
    rec["version"] = int(rec.get("version", 1)) + 1


def public(rec):
    """Strip internal bookkeeping keys before serialisation."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_key(rec, field):
    """Sort by the named timestamp field, tie-broken by insertion order."""
    return (rec.get(field) or "", rec.get("_seq", 0))
