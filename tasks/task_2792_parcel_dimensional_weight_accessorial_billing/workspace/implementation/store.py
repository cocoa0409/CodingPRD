"""In-memory data store plus the logical clock (PRD 2.4).

Storage is process-local Python dicts keyed by id.  Nothing is ever seeded:
every record in here is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, date, timedelta, timezone

# PRD 2.4: before the clock has ever been set it reads exactly this instant and
# never falls back to the machine's wall clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.shipper_accounts = {}
        self.rate_contracts = {}
        self.service_levels = {}
        self.surcharge_windows = {}
        self.shipments = {}
        self.dimension_scans = {}
        self.accessorial_charges = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.billing_adjustments = {}
        self.disputes = {}
        self.evidence_items = {}
        self.guarantee_claims = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------

def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 instant; returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_day(value):
    """Parse a strict YYYY-MM-DD calendar date; returns None when unparseable."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        return None


def day_string(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def date_of(instant):
    return instant.astimezone(timezone.utc).date()


def add_days(day_str, days):
    d = parse_day(day_str)
    return day_string(d + timedelta(days=days))


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_record(versioned=True):
    """Mint id/created_at (+updated_at/version) from the logical clock."""
    stamp = iso(now())
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = iso(now())
    rec["version"] = rec.get("version", 1) + 1


def order_key(rec):
    """Default list ordering: created_at ascending, insertion order as the
    stable tie-break.  The record id is never an ordering key."""
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def sorted_records(records):
    return sorted(records, key=order_key)
