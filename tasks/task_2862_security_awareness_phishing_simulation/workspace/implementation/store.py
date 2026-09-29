"""In-memory store, logical clock and shared primitives.

The store starts completely empty on every boot -- nothing is seeded.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD 2.5 -- before any client sets it, the logical clock reads exactly this instant.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d{1,9})?([Zz]|[+-]\d{2}:?\d{2})$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.employees = {}
        self.modules = {}
        self.assignments = {}
        self.notices = {}
        self.consequences = {}
        self.templates = {}
        self.campaigns = {}
        self.deliveries = {}
        self.events = {}
        self.interventions = {}
        self.incidents = {}
        self.windows = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    return store.clock


# ---------------------------------------------------------------- time helpers
def parse_instant(value):
    """Parse an ISO-8601 instant. Returns None when the value is not parseable."""
    if not isinstance(value, str):
        return None
    if not ISO_RE.match(value.strip()):
        return None
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date at UTC midnight."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        d = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def add_days(dt, days):
    """Whole days added to an instant, never truncated to midnight."""
    if dt is None:
        return None
    return dt + timedelta(days=days)


def floor_days(later, earlier):
    """floor((later - earlier) / 86400 seconds)."""
    delta = (later - earlier).total_seconds()
    return int(delta // 86400)


def floor_minutes(later, earlier):
    delta = (later - earlier).total_seconds()
    return int(delta // 60)


# ------------------------------------------------------------ number helpers
def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def rate(numerator, denominator, places=4):
    if denominator == 0:
        return None
    value = Decimal(numerator) / Decimal(denominator)
    return float(round_half_up(value, places))


def money2(value):
    return float(round_half_up(value, 2))


# ------------------------------------------------------------- row primitives
def new_row(versioned=True):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": store.clock,
        "_seq": store.next_seq(),
    }
    if versioned:
        row["updated_at"] = store.clock
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = store.clock
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """Default list ordering: created_at ascending, stable by insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
