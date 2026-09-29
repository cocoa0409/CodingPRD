"""In-memory data store and the logical clock (PRD sections 2.4 and 2.5).

The store starts completely empty on every boot. Nothing is seeded, preloaded or
hardcoded -- every entity is built by callers through the declared API surface.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from flask import g

# --- logical clock ---------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# --- collections -----------------------------------------------------------
MANUFACTURERS = {}
HEARING_ROOMS = {}
DEALERS = {}
LICENSE_APPLICATIONS = {}
SALESPERSONS = {}
FRANCHISE_FILINGS = {}
PROTESTS = {}
MARKET_STUDIES = {}
EVIDENCE_SUBMISSIONS = {}
WARRANTY_RATE_DISPUTES = {}
CONSUMER_COMPLAINTS = {}

COLLECTIONS = {
    "manufacturer": MANUFACTURERS,
    "hearing_room": HEARING_ROOMS,
    "dealer": DEALERS,
    "license_application": LICENSE_APPLICATIONS,
    "salesperson": SALESPERSONS,
    "franchise_filing": FRANCHISE_FILINGS,
    "protest": PROTESTS,
    "market_study": MARKET_STUDIES,
    "evidence_submission": EVIDENCE_SUBMISSIONS,
    "warranty_rate_dispute": WARRANTY_RATE_DISPUTES,
    "consumer_complaint": CONSUMER_COMPLAINTS,
}

_STATE = {"clock": CLOCK_EPOCH, "seq": 0}


def reset():
    for store in COLLECTIONS.values():
        store.clear()
    _STATE["clock"] = CLOCK_EPOCH
    _STATE["seq"] = 0


# --- clock accessors -------------------------------------------------------
def now():
    """The current logical instant (an aware UTC datetime)."""
    return _STATE["clock"]


def today():
    """The date part of the current logical instant."""
    return _STATE["clock"].date()


def set_clock(instant):
    _STATE["clock"] = instant


def iso_instant(value):
    """Render an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    utc = aware.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second,
        utc.microsecond // 1000,
    )


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def days_between(later, earlier):
    return (later - earlier).days


def plus_days(value, count):
    if value is None:
        return None
    return value + timedelta(days=count)


# --- record lifecycle ------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def insert(kind, record, versioned=True):
    """Persist a record, stamping the common system fields."""
    store = COLLECTIONS[kind]
    record["id"] = record.get("id") or new_id()
    record["__kind"] = kind
    record["__seq"] = _next_seq()
    record["created_at"] = now()
    if versioned:
        record["updated_at"] = now()
        record["version"] = 1
    store[record["id"]] = record
    return record


def _touched_set():
    marks = getattr(g, "_touched_records", None)
    if marks is None:
        marks = set()
        g._touched_records = marks
    return marks


def touch(record):
    """Refresh updated_at and increment version -- at most once per request."""
    if record is None or "version" not in record:
        return record
    marks = _touched_set()
    key = (record.get("__kind"), record.get("id"))
    if key in marks:
        return record
    marks.add(key)
    record["updated_at"] = now()
    record["version"] = record["version"] + 1
    return record


# --- lookups ---------------------------------------------------------------
def get(kind, record_id):
    if not isinstance(record_id, str):
        return None
    return COLLECTIONS[kind].get(record_id)


def ordered(kind):
    """Every record of a kind in created_at ascending order.

    The logical clock never moves backwards, so insertion sequence is exactly
    created_at ascending, and it also settles ties deterministically.
    """
    return sorted(COLLECTIONS[kind].values(), key=lambda r: (r["created_at"], r["__seq"]))


def where(kind, **criteria):
    rows = []
    for record in ordered(kind):
        if all(record.get(key) == value for key, value in criteria.items()):
            rows.append(record)
    return rows
