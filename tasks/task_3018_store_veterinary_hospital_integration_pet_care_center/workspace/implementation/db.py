"""In-memory data store — starts empty on every boot, no seeding, no disk."""

import uuid
from datetime import datetime, timedelta, timezone

TABLES = (
    "stores",
    "members",
    "pets",
    "breed_rules",
    "bays",
    "bookings",
    "screenings",
    "encounters",
    "clinics",
    "visits",
    "certificates",
    "authorizations",
    "pharmacy_orders",
    "incidents",
    "cross_sells",
    "packages",
    "cycles",
    "enrollments",
)

db = {name: {} for name in TABLES}

# scheduled (deferred) action queue: (clock_value, kind, payload)
SCHEDULED = []

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

clock = {"current": CLOCK_START, "highest": CLOCK_START}


def new_id():
    return str(uuid.uuid4())


def now():
    """The current logical clock instant (never wall-clock time)."""
    return clock["current"]


def iso(dt):
    """Second-precision UTC ISO 8601, e.g. 2026-09-01T00:00:00Z."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 instant from a caller (or the golden clock literal)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError("invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def new_row(versioned=True, common=True):
    stamp = now()
    # `clock_at` is the clock value this row was last created, read or mutated
    # at; it is what the backdating rule of PRD §2.5 compares against.
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp,
           "clock_at": stamp}
    if versioned:
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version when versioned."""
    row["updated_at"] = now()
    row["clock_at"] = now()
    if "version" in row and row["version"] is not None:
        row["version"] += 1


def mark_read(row):
    """A read counts as a use of the row for the backdating rule."""
    if row is not None:
        row["clock_at"] = now()


def add(table, row):
    db[table][row["id"]] = row
    return row


def get(table, row_id):
    return db[table].get(row_id)


def rows(table):
    return list(db[table].values())


def plus_days(instant, days):
    return instant + timedelta(days=days)


def month_end_after(instant):
    """Last day of the calendar month following `instant`'s month, at 23:59:59Z."""
    year, month = instant.year, instant.month
    if month == 12:
        year_next, month_next = year + 1, 1
    else:
        year_next, month_next = year, month + 1
    if month_next == 12:
        first_of_after = datetime(year_next + 1, 1, 1, tzinfo=timezone.utc)
    else:
        first_of_after = datetime(year_next, month_next + 1, 1, tzinfo=timezone.utc)
    return first_of_after - timedelta(seconds=1)


def reset():
    for name in TABLES:
        db[name].clear()
    del SCHEDULED[:]
    clock["current"] = CLOCK_START
    clock["highest"] = CLOCK_START