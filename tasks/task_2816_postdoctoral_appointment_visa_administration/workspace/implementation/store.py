"""In-memory data store, logical clock, and record bookkeeping.

Storage is process-local and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded anywhere in this module.
"""
import itertools
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# The logical clock reads exactly this instant until it is explicitly set.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.postdocs = {}
        self.mentors = {}
        self.funding_sources = {}
        self.laboratories = {}
        self.appointments = {}
        self.visa_cases = {}
        self.development_documents = {}
        self.export_control_reviews = {}
        self.lab_access_grants = {}
        self.reappointment_reviews = {}
        self.grievances = {}
        self.exit_records = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def now(self):
        return self.clock

    def today(self):
        return self.clock.date()

    def next_seq(self):
        return next(self._seq)


store = Store()


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_record():
    now = store.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version once per request."""
    if record is None:
        return
    touched = getattr(g, "touched_records", None)
    if touched is None:
        touched = set()
        g.touched_records = touched
    record["updated_at"] = store.now()
    if record["id"] not in touched:
        touched.add(record["id"])
        record["version"] = record["version"] + 1


def sorted_records(records):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# decimal / date helpers
# --------------------------------------------------------------------------

TWO_PLACES = Decimal("0.01")
ONE_PLACE = Decimal("0.1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not a number: %r" % (value,))


def q2(value):
    return dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def q1(value):
    return dec(value).quantize(ONE_PLACE, rounding=ROUND_HALF_UP)


def money_out(value):
    if value is None:
        return None
    return float(q2(value))


def number_out(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def iso_ts(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day, value.hour, value.minute,
        value.second, value.microsecond // 1000,
    )


def iso_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_date_str(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime_str(value):
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(value, days):
    return value + timedelta(days=int(days))


def day_span(start, end):
    """Inclusive day count between two dates (<= 0 when they do not overlap)."""
    return (end - start).days + 1


def end_of_day_ms(value):
    """23:59:59.999Z on the supplied date."""
    return datetime(value.year, value.month, value.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


__all__ = [
    "store", "Store", "DEFAULT_CLOCK", "new_record", "touch", "sorted_records",
    "dec", "q2", "q1", "money_out", "number_out", "iso_ts", "iso_date",
    "parse_date_str", "parse_datetime_str", "add_days", "day_span", "end_of_day_ms",
    "date", "datetime", "timedelta", "timezone", "Decimal",
]
