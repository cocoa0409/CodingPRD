"""In-memory data store.

Everything lives in process memory: plain dicts keyed by id.  Nothing is ever
written to disk, to /tmp, or to any cache, so a fresh ``start.sh`` invocation
always boots into a pristine, empty database.  No entity is seeded here or
anywhere else at startup -- every row a test needs is created through the
declared API surface (POST /engineers, POST /assignments, ... ).

The service never reads wall-clock time: it carries a logical clock that starts
at 2026-09-01T00:00:00Z and moves only when POST /_clock/set_current_utc is
called by a PlatformAdmin.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# Logical-clock default before any POST /_clock/set_current_utc call.
DEFAULT_NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Every entity this API declares, as §1.1 names them.
COLLECTIONS = (
    "engineers",
    "customers",
    "assignments",
    "quotes",
    "quote_lines",
    "products",
    "instrument_units",
    "warranty_plans",
    "warranty_claims",
    "service_centers",
    "support_tickets",
    "escalation_ledger",
    "backorders",
    "gear_exchanges",
    "certification_attempts",
)


class Store(object):
    """Flat, process-local row store.  Starts empty on every boot."""

    def __init__(self):
        self.clear()

    def clear(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.seq = itertools.count(1)
        self.clock = DEFAULT_NOW

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self.seq)

    def now(self):
        return self.clock

    def add(self, collection, row):
        getattr(self, collection)[row["id"]] = row
        return row

    def get(self, collection, ident):
        return getattr(self, collection).get(ident)

    def all(self, collection):
        return list(getattr(self, collection).values())

    def where(self, collection, **filters):
        out = []
        for row in self.all(collection):
            if all(row.get(key) == value for key, value in filters.items()):
                out.append(row)
        return out


DB = Store()


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def iso(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.10)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"),
                         value.microsecond // 1000)


R = iso  # shorthand used across the code base


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, else None."""
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
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(instant, days):
    return instant + timedelta(days=days)


def add_months(instant, months):
    """Calendar-month arithmetic used by term_months / 12-month validity."""
    month_index = instant.month - 1 + months
    year = instant.year + month_index // 12
    month = month_index % 12 + 1
    day = min(instant.day, 28)
    return instant.replace(year=year, month=month, day=day)


def seconds_between(later, earlier):
    return (later - earlier).total_seconds()