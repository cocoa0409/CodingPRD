"""In-memory data store and the logical clock.

The store starts empty on every boot: nothing here is seeded, preloaded or
hardcoded.  Every entity a caller needs is created through the declared API.
"""

import uuid
from datetime import datetime, timedelta, timezone

# Each collection is a dict keyed by the row id; insertion order is preserved
# and doubles as the creation order used for default list ordering.
DRIVERS = {}
ENROLLMENTS = {}
VEHICLES = {}
AGREEMENTS = {}
WEEKS = {}
MAINTENANCE_EVENTS = {}
PAYMENTS = {}
PURCHASE_OPTIONS = {}
PLATFORM_CHECKS = {}
FLEET_FACTS = {}

# The logical clock.  Initial value is fixed by the contract; the server never
# falls back to host wall-clock time.
INITIAL_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": INITIAL_CLOCK}


def now():
    return _clock["now"]


def set_clock(instant):
    _clock["now"] = instant


def reset():
    """Used only by the test harness' fresh-process boot; never seeds data."""
    for collection in (DRIVERS, ENROLLMENTS, VEHICLES, AGREEMENTS, WEEKS,
                       MAINTENANCE_EVENTS, PAYMENTS, PURCHASE_OPTIONS,
                       PLATFORM_CHECKS, FLEET_FACTS):
        collection.clear()
    _clock["now"] = INITIAL_CLOCK


def new_id():
    return str(uuid.uuid4())


def fmt(instant):
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    if instant.microsecond == 0:
        return instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def now_iso():
    return fmt(now())


def parse_iso(value):
    """Accept either a stored datetime or an ISO 8601 string."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)


def stamp_created(row):
    instant = now()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row