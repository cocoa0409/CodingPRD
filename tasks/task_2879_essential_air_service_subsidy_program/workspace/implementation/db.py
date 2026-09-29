"""In-memory store, the program's logical clock and numeric/temporal helpers.

Nothing here is seeded: every register starts empty on every boot and is filled
exclusively through the declared API surface.  The single declared default is the
logical clock, which reads 2026-08-01T00:00:00Z before any caller moves it
(PRD section 2.5).
"""

import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "communities",
    "carriers",
    "aircraft_types",
    "fuel_indices",
    "determinations",
    "solicitations",
    "proposals",
    "preferences",
    "agreements",
    "periods",
    "payments",
    "reviews",
    "petitions",
    "renegotiations",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# ---------------------------------------------------------------------------
# identity / timestamps
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now():
    return store.clock


def now_iso():
    return fmt_ts(store.clock)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    if dt.utcoffset() != timedelta(0):
        return None
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def month_of(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def month_index(ym):
    year = int(ym[0:4])
    month = int(ym[5:7])
    return year * 12 + (month - 1)


def month_from_index(index):
    return "%04d-%02d" % (index // 12, index % 12 + 1)


def month_add(ym, n):
    return month_from_index(month_index(ym) + n)


def months_inclusive(start_ym, end_ym):
    return month_index(end_ym) - month_index(start_ym) + 1


# ---------------------------------------------------------------------------
# decimal helpers -- all monetary and ratio rounding is round-half-up
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


_EXP = {n: Decimal(1).scaleb(-n) for n in range(0, 9)}


def q(value, places):
    return dec(value).quantize(_EXP[places], rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def dec_places(value):
    """Number of decimal places carried by a JSON-parsed number."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return 0
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            return 0
        return max(0, -exponent)
    if isinstance(value, float):
        text = repr(value)
        if "." in text:
            return len(text.split(".")[1])
        return 0
    return 0


# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------
def base_row(versioned=True):
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a real mutation: refresh updated_at and bump version (PRD 2.11)."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
