"""In-memory data store and the server-side logical clock (PRD section 2.5).

Storage is plain Python dictionaries keyed by id.  Nothing is persisted and
nothing is seeded: every boot starts completely empty.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "distributors",
    "artists",
    "deals",
    "releases",
    "agreements",
    "spends",
    "rate_cards",
    "reports",
    "lines",
    "runs",
    "statements",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self._clock = DEFAULT_CLOCK

    # -- logical clock -------------------------------------------------
    def now(self):
        return self._clock

    def set_now(self, instant):
        self._clock = instant

    def today(self):
        """The clock's UTC calendar date."""
        return self._clock.date()

    # -- identity / ordering ------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------
# Instant and date helpers
# ---------------------------------------------------------------------

def iso_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO 8601 instant, truncated to millisecond precision."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def parse_date(text):
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_str(value):
    if value is None:
        return None
    return value.isoformat()


def add_days(instant, days):
    return instant + timedelta(days=days)


# ---------------------------------------------------------------------
# Money / percentage helpers.  Never float.
# ---------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_pct_4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def largest_remainder(total, weights, tiebreaks):
    """Distribute `total` across `weights` by the largest-remainder method.

    Leftover cents go to the largest fractional part first; ties break on the
    supplied tiebreak key ascending (creation order).
    """
    count = len(weights)
    if count == 0:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0 or total == 0:
        return [0] * count
    exact = [Decimal(total) * Decimal(w) / Decimal(weight_sum) for w in weights]
    floors = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
    leftover = total - sum(floors)
    order = sorted(
        range(count),
        key=lambda i: (-(exact[i] - Decimal(floors[i])), tiebreaks[i]),
    )
    index = 0
    while leftover > 0 and index < count:
        floors[order[index]] += 1
        leftover -= 1
        index += 1
    return floors


# ---------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------

def base_record(mutable=True):
    """Common system fields (PRD section 2.4)."""
    now = store.now()
    record = {
        "id": new_id(),
        "created_at": iso_instant(now),
        "_seq": store.next_seq(),
    }
    if mutable:
        record["updated_at"] = iso_instant(now)
        record["version"] = 1
    return record


def touch(record):
    """Register a mutation: bump version by exactly one, refresh updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = iso_instant(store.now())
    return record


def ordered(records):
    """All list endpoints order by created_at ascending (PRD section 2.3).

    `_seq` is a monotonic write counter, so it is the creation order even when
    the logical clock has been repositioned between two writes.
    """
    return sorted(records, key=lambda r: r["_seq"])
