"""In-memory store, logical clock and the numeric primitives.

Storage is process-local: plain dicts keyed by id. Nothing is written to disk
and nothing is seeded at import time, so a fresh `bash start.sh` yields a
pristine store. Every entity a caller needs is created through the declared
API surface.

Money is integer cents. Rates are exact Decimals. Final values written to a
field are rounded half-up, per PRD §2.4.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Numeric primitives
# --------------------------------------------------------------------------

CENT = Decimal("1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    """round_half_up to 2dp, returned as int cents."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def r3(value):
    return dec(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def r4(value):
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    d = dec(value)
    return int(d.to_integral_value(rounding="ROUND_CEILING"))


def trunc_int(value):
    d = dec(value)
    return int(d.to_integral_value(rounding="ROUND_DOWN"))


# calculations.insurance_tier_ceiling — boundary comparisons are STRICT <.
def insurance_tier_ceiling(amount_cents):
    a = int(amount_cents)
    if a < 20000:
        return 30000
    if a < 50000:
        return 50000
    if a < 100000:
        return 100000
    if a < 200000:
        return 200000
    return 300000


# --------------------------------------------------------------------------
# Logical clock — reads 2026-09-01T00:00:00Z before any call, never wall time.
# --------------------------------------------------------------------------

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 instant; raise ValueError on anything unparseable."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits.

    PRD §2.4 fixes the resource timestamp form as three fractional digits, e.g.
    `2025-05-24T10:30:00.123Z`; a whole-second instant is rendered with explicit
    zeroes rather than shortened.
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


class Clock:
    def __init__(self):
        self.current = CLOCK_START

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt
        return self.current

    def advance(self, dt):
        if dt > self.current:
            self.current = dt
        else:
            self.current = dt
        return self.current

    def stamp(self):
        return fmt(self.current)

    def days(self, a, b):
        return int((b - a).total_seconds() // 86400)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class Store:
    """Process-local collections. Empty on every boot."""

    COLLECTIONS = (
        "routes", "itineraries", "price_observations", "demand_curves",
        "watch_subscriptions", "price_freezes", "protections", "claims",
        "change_events", "rebooking_options", "payments", "hedging_positions",
        "risk_pools", "destination_options",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = Clock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def mint(self):
        return str(uuid.uuid4())

    def insert(self, collection, row):
        getattr(self, collection)[row["id"]] = row
        return row

    def all(self, collection):
        return list(getattr(self, collection).values())

    def get(self, collection, ident):
        return getattr(self, collection).get(ident)


DB = Store()


def touch(row):
    """A mutation refreshes updated_at and advances version by 1."""
    row["version"] = int(row.get("version", 1)) + 1
    row["updated_at"] = DB.clock.stamp()
    return row


def new_row(**fields):
    now = DB.clock.stamp()
    row = {
        "id": DB.mint(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created_dt": DB.clock.now(),
    }
    row.update(fields)
    return row


def public(row):
    """Serializable view: internal ordering keys are stripped."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_rows(collection, predicate=None, sort_key=None):
    rows = list(getattr(DB, collection).values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    if sort_key is not None:
        rows.sort(key=sort_key)
    return [public(r) for r in rows]


def iso(dt):
    """Render an instant in the declared timestamp form: three fractional
    digits with a `Z` suffix (PRD §2.4)."""
    return fmt(dt)


def hours_later(hours):
    return DB.clock.now() + timedelta(hours=hours)


def days_later(days):
    return DB.clock.now() + timedelta(days=days)