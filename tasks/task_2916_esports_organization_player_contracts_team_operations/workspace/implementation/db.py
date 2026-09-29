"""In-memory store, the logical clock and instant/record helpers.

PRD section 2.5: the service never reads wall-clock time.  Before any client sets it the
logical clock reads exactly 2026-08-01T00:00:00Z.

PRD section 2.4: every resource carries a server-minted UUID `id`, `created_at`,
`updated_at` and an integer `version` that starts at 1 and increases by exactly 1 on
every mutation, including mutations produced as a cascade side effect.

The store starts EMPTY on every boot.  Nothing is ever seeded here.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# PRD section 2.5 -- the fixed initial reading of the logical clock.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# PRD section 2.7 -- duration discipline.
MONTH_DAYS = 30
SEASON_DAYS = 365
MONTHS_PER_YEAR = 12
HOUR_SECONDS = 3600
DAY_SECONDS = 86400
MINUTES_PER_HOUR = 60
WEEK_DAYS = 7
BP_DENOMINATOR = 10000


class Store(object):
    """Every collection is a plain dict keyed by the resource id."""

    def __init__(self):
        self.leagues = {}
        self.organizations = {}
        self.players = {}
        self.offers = {}
        self.contracts = {}
        self.team_houses = {}
        self.practice_blocks = {}
        self.deals = {}
        self.assignments = {}
        self.distributions = {}
        self.allocations = {}
        self.roster_moves = {}
        self.current_utc = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def reset(self):
        self.__init__()


store = Store()


def now():
    """The current logical instant."""
    return store.current_utc


def set_clock(instant):
    store.current_utc = instant


# --------------------------------------------------------------------------------------
# instants
# --------------------------------------------------------------------------------------

def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.4/2.5)."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        instant.second,
        instant.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO 8601 instant.  Returns None when the value is not parseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def add_hours(instant, hours):
    return instant + timedelta(hours=hours)


def add_days(instant, days):
    return instant + timedelta(days=days)


def whole_days_between(start, end):
    """floor((end - start) / 1 day) -- may be negative."""
    seconds = (end - start).total_seconds()
    return int(seconds // DAY_SECONDS)


def whole_minutes_between(start, end):
    seconds = (end - start).total_seconds()
    return int(seconds // 60)


def week_start(instant):
    """The most recent Monday 00:00:00Z at or before `instant` (PRD section 3.5)."""
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


# --------------------------------------------------------------------------------------
# arithmetic (PRD section 2.7)
# --------------------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/int/Fraction to a whole cent, halves away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_bp(amount, bp):
    """round_half_up(amount * bp / 10000)."""
    return round_half_up(Decimal(int(amount)) * Decimal(int(bp)) / Decimal(BP_DENOMINATOR))


def floor_div(numerator, denominator):
    """Truncate towards negative infinity on integers."""
    return int(numerator) // int(denominator)


def ceil_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------------------

def insert(collection, record):
    record["id"] = str(uuid.uuid4())
    stamp = now()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_seq"] = store.next_seq()
    collection[record["id"]] = record
    return record


def touch(record):
    """PRD section 2.4: refresh updated_at and increment version by exactly 1."""
    record["updated_at"] = now()
    record["version"] = int(record["version"]) + 1
    return record


def in_creation_order(records):
    """PRD section 2.3: list results are ordered by created_at ascending.

    The logical clock can be frozen, so many records share one created_at; the
    monotonic insertion sequence is the stable tiebreak.
    """
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
