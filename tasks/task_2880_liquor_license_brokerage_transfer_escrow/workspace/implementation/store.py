"""In-memory data store and the server-held logical clock.

The store starts completely empty on every boot; nothing is seeded.
Nothing in this system reads wall-clock time for domain instants: the logical
clock reads exactly 2026-08-01T00:00:00Z at startup (PRD 2.4).
"""

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

LOGICAL_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.counties = {}
        self.sellers = {}
        self.buyers = {}
        self.brokerages = {}
        self.licenses = {}
        self.premises = {}
        self.listings = {}
        self.agreements = {}
        self.disclosures = {}
        self.applications = {}
        self.protests = {}
        self.ledger = {}
        self.filings = {}
        self.clock = LOGICAL_CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical instant."""
    return db.clock


def set_clock(instant):
    db.clock = instant
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(value):
    """ISO 8601 UTC instant with exactly three fractional-second digits."""
    if value is None:
        return None
    if isinstance(value, datetime):
        v = value.astimezone(timezone.utc)
        return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
            v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000)
    return value


def add_days(instant, days):
    """Day arithmetic: adds whole days, keeping the same time-of-day."""
    return instant + timedelta(days=int(days))


def add_months(instant, months):
    """Calendar-month arithmetic: preserves day-of-month, clamping short months."""
    months = int(months)
    total = (instant.year * 12) + (instant.month - 1) + months
    year = total // 12
    month = (total % 12) + 1
    day = min(instant.day, calendar.monthrange(year, month)[1])
    return instant.replace(year=year, month=month, day=day)


def whole_day_diff(later_date, earlier_date):
    """Whole UTC calendar-day difference between two date objects."""
    return (later_date - earlier_date).days


def make_record(fields, versioned=True):
    """Build a record: server-minted id first, then the entity fields, then the
    common properties of PRD 2.5."""
    rec = {"id": new_id()}
    rec.update(fields)
    stamp = now()
    rec["created_at"] = stamp
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def bump(rec):
    """A mutation: refresh updated_at and advance version by exactly one."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def public(rec):
    """Serialise a record: drop internal keys, render datetimes."""
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        elif isinstance(value, date):
            out[key] = "%04d-%02d-%02d" % (value.year, value.month, value.day)
        else:
            out[key] = value
    return out


def public_list(recs):
    return [public(r) for r in recs]


def sorted_by_created(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


def sorted_ledger(recs):
    """Escrow ledger append order: occurred_at ASC, created_at ASC tie-break."""
    return sorted(recs, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))
