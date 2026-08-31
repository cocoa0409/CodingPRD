"""In-memory store, logical clock, row helpers and rounding discipline.

Storage is process-local Python dicts keyed by id.  The store starts EMPTY on
every boot: nothing is seeded, preloaded or hardcoded.
"""
import re
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# The logical clock reads exactly this at startup and never falls back to the
# host wall clock (PRD 2.5).
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

lock = threading.RLock()

_COLLECTIONS = (
    "trading_desks",
    "elevator_locations",
    "discount_schedules",
    "risk_limits",
    "rail_fleets",
    "bids",
    "hedge_positions",
    "purchase_contracts",
    "pricing_orders",
    "margin_calls",
    "delivery_tickets",
    "freight_bookings",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.now = CLOCK_START
        self._seq = 0
        for name in _COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# Rounding: always half-up, midpoint rounds away from zero (PRD 2.6).
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def _round(value, places):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def r2(value):
    return _round(value, 2)


def r4(value):
    return _round(value, 4)


def r0(value):
    """Half-up to a whole number, returned as int."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    """Number of whole steps, rounding any partial step up."""
    n = D(numerator)
    d = D(denominator)
    if n <= 0:
        return 0
    q = n / d
    whole = int(q)
    if D(whole) < q:
        whole += 1
    return whole


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 UTC datetime; return None when malformed."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro,
                        tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        base = base - sign * offset
    return base


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; return None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc).date()
    except ValueError:
        return None


def is_futures_month(value):
    if not isinstance(value, str):
        return False
    m = _MONTH_RE.match(value.strip())
    if not m:
        return False
    return 1 <= int(m.group(2)) <= 12


def end_of_day(date_obj):
    """23:59:59.999Z of a calendar date."""
    return datetime(date_obj.year, date_obj.month, date_obj.day,
                    23, 59, 59, 999000, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def new_row(versioned=True):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": db.now,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = db.now
        row["version"] = 1
    return row


def touch(row):
    if "version" in row:
        row["updated_at"] = db.now
        row["version"] = row["version"] + 1


def apply_changes(row, changes):
    """Write changes; bump version/updated_at once when anything really moved."""
    dirty = False
    for key, value in changes.items():
        old = row.get(key, "__missing__")
        same = False
        if old is not None and value is not None and not isinstance(old, str) \
                and not isinstance(value, str) and old != "__missing__":
            try:
                same = (D(old) == D(value))
            except Exception:
                same = (old == value)
        else:
            same = (old == value)
        if not same:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def num(value):
    """JSON-friendly rendering of a stored Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
