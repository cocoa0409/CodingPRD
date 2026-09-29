"""In-memory data store, the logical UTC clock and shared constants.

The store starts EMPTY on every boot.  No entity is ever seeded, preloaded or
hardcoded here: every row is created through a declared endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD s1.3 calculation constants / PRD s3)
# ---------------------------------------------------------------------------
API_PREFIX = "/valet"

ROLES = {
    "PlatformAdmin",
    "PropertyManager",
    "ValetOpsManager",
    "ComplianceOfficer",
    "Valet",
    "Resident",
    "BillingAnalyst",
}

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]  # index == date.weekday()
WEEKDAY_SET = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"}

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# statement settlement
PARTIAL_NIGHT_WEIGHT = Decimal("0.5")
SLA_TIER1_CREDIT_BPS = 500
SLA_TIER2_CREDIT_BPS = 1200
SLA_TIER2_ENTRY_BPS = 2000

# resident fines
FINE_BASE_CENTS = {
    "EARLY_SET_OUT": 2500,
    "IMPROPER_CONTAINER": 1500,
    "RECYCLING_CONTAMINATION": 5000,
}
FINE_ESCALATION_MULTIPLIER = {1: Decimal("0.5"), 2: Decimal("1.5"), 3: Decimal("2.0")}
SEASONAL_PEAK_INDEX = 120
SEASONAL_PEAK_MULTIPLIER = Decimal("1.25")
FINE_FLOOR_CENTS = 1000
MONTHLY_FINE_CAP_CENTS = 15000
FINE_LOOKBACK_DAYS = 90
AUTO_FINE_ORDINAL = 3
MAX_DISPUTE_ROUNDS = 2
DELINQUENCY_THRESHOLD_CENTS = 7500

# contractor classification
CONTROL_WEIGHT_EQUIPMENT = 30
CONTROL_WEIGHT_FIXED_SCHEDULE = 25
CONTROL_WEIGHT_FULLTIME_HOURS = 25
CONTROL_WEIGHT_EXCLUSIVITY = 20
OBSERVED_FULLTIME_WEEKLY_HOURS = Decimal("30")
OBSERVED_EXCLUSIVITY_MIN_ROUTES = 3
OBSERVED_WINDOW_DAYS = 7
CLASSIFICATION_W2_SCORE_THRESHOLD = 70

# service night verification
VERIFICATION_COVERAGE_THRESHOLD_BPS = 7500
LIVE_ROUTE_STATUSES = ("ASSIGNED", "ACCEPTED", "IN_PROGRESS", "COMPLETED")
OPEN_ROUTE_STATUSES = ("ASSIGNED", "ACCEPTED", "IN_PROGRESS")

# compactor incidents
ACK_WINDOW_HOURS = {"JAM": 4, "OVERFLOW": 24}
PROPERTY_SUSPENSION_ESCALATION_LEVEL = 2

MAKEUP_WINDOW_DAYS = 14

UNIT_BASE = 100  # unit range is [101, 100 + unit_count]

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD s2.7).  Never reads the host wall clock.
# ---------------------------------------------------------------------------
class Clock(object):
    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt.astimezone(timezone.utc)
        return self.current

    def reset(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


clock = Clock()


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return iso(clock.now())


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_period(value):
    """Parse a strict YYYY-MM month string.  Returns (year, month) or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 7 or text[4] != "-":
        return None
    try:
        y = int(text[0:4])
        m = int(text[5:7])
    except ValueError:
        return None
    if m < 1 or m > 12:
        return None
    return (y, m)


def days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - datetime(year, month, 1)).days


def period_bounds(period):
    """Return (first_date, last_date) of a YYYY-MM period string."""
    y, m = parse_period(period)
    first = datetime(y, m, 1).date()
    last = (datetime(y, m, 1) + timedelta(days=days_in_month(y, m) - 1)).date()
    return first, last


def weekday_name(d):
    return WEEKDAYS[d.weekday()]


def rhu(value):
    """round_half_up to a whole integer."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """round_half_up to two decimals, returned as Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal as a JSON number without trailing-zero noise."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value == int(value):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.properties = {}
        self.contracts = {}
        self.residents = {}
        self.contractors = {}
        self.nights = {}
        self.routes = {}
        self.scans = {}
        self.fines = {}
        self.incidents = {}
        self.statements = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def reset(self):
        self.__init__()


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(row):
    """Apply the four common system-managed fields to a fresh row."""
    ts = now_iso()
    row["id"] = row.get("id") or new_id()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Register a mutation: refresh updated_at and increment version by 1."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows):
    """Default collection ordering: created_at ascending (insertion-stable)."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
