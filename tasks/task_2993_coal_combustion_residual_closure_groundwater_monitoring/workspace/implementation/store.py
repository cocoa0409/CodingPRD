"""In-memory data store and the logical regulatory clock.

Storage is process-local only: every dict below starts empty on each boot and
nothing is ever written to disk.  No entity is ever seeded.
"""
import calendar
import datetime as _dt
import itertools
import random
import string
import threading
import uuid
from decimal import Decimal

LOCK = threading.RLock()

# ---------------------------------------------------------------- collections
units = {}
professionals = {}
stability_assessments = {}
wells = {}
programs = {}
sampling_events = {}
analytical_results = {}
statistical_evaluations = {}
closure_plans = {}
extension_requests = {}
reuse_agreements = {}
reuse_shipments = {}
cap_inspections = {}
public_postings = {}

_seq = itertools.count(1)

# --------------------------------------------------------------- logical clock
# PRD 2.5: before any client sets it the logical clock reads exactly
# 2026-08-01T00:00:00Z and the server never falls back to real wall time.
CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def clock_now():
    return _clock["now"]


def clock_set(value):
    _clock["now"] = value
    return value


def today():
    """Calendar date of the logical clock in UTC."""
    return _clock["now"].date()


def iso_instant(value):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    v = value.astimezone(_dt.timezone.utc)
    return v.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (v.microsecond // 1000)


def wall_now():
    return _dt.datetime.now(_dt.timezone.utc)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ------------------------------------------------------------ record lifecycle
def stamp_new(record, versioned=True):
    """Attach identity + common fields to a brand new record."""
    now = wall_now()
    record["id"] = new_id()
    record["created_at"] = iso_instant(now)
    record["_seq"] = next_seq()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Persisted mutation: bump the mutation counter and refresh updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = iso_instant(wall_now())
    return record


def sort_key(record):
    return (record["created_at"], record["_seq"])


def ordered(values):
    """List results ordered by created_at ascending (PRD 2.3)."""
    return sorted(values, key=sort_key)


# ------------------------------------------------------------------ date maths
def parse_date(text):
    try:
        return _dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def parse_instant(text):
    """Accept an ISO-8601 instant with Z or a numeric offset; return UTC."""
    if not isinstance(text, str):
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        value = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(_dt.timezone.utc)


def fmt_date(value):
    return value.isoformat()


def add_days(date_text, days):
    return fmt_date(parse_date(date_text) + _dt.timedelta(days=days))


def add_months(date_text, months):
    """Advance the calendar by `months`, keeping the day of month and clamping
    to the last day of a shorter target month."""
    d = parse_date(date_text)
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return fmt_date(_dt.date(year, month, day))


def day_diff(later_text, earlier_text):
    return (parse_date(later_text) - parse_date(earlier_text)).days


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
