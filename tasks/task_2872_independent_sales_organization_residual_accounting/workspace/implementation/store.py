"""In-memory store, logical clock and numeric/date helpers.

The store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded anywhere in this module or at import time.
"""
import calendar
import itertools
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- constants (PRD section 3) ----------------------------------------------
MAX_OVERRIDE_LEVELS = 3
MAX_HIERARCHY_DEPTH = 4
ATTRITION_HOLD_THRESHOLD_BPS = 2500
CLAWBACK_WINDOW_DAYS = 270
MIN_PAYOUT_CENTS = 2500
MAX_TOTAL_RECOUPMENT_PCT = Decimal("0.5")
TIER_1_CEILING_CENTS = 50000
TIER_2_CEILING_CENTS = 150000
VESTING_CLIFF_MONTHS = 12
VESTING_STEP_MONTHS = 12
VESTING_STEP_PCT = 25
VESTING_BUYOUT_MULTIPLE = 24
MINIMUM_SHARE_PCT = Decimal("0.5")
BOOTSTRAP_ADVANCE_CEILING_CENTS = 250000
MAX_ADVANCE_EXPOSURE_MULTIPLE = 6

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def round_half_up(value):
    """Round a Decimal/int/Fraction to the nearest whole unit, halves away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_instant(text):
    """Parse an ISO-8601 instant; returns a timezone-aware UTC datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_instant(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def parse_date(text):
    if not isinstance(text, str) or not DATE_RE.match(text):
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def is_month(text):
    return isinstance(text, str) and bool(MONTH_RE.match(text))


def month_index(month):
    """YYYY-MM -> absolute month ordinal."""
    year = int(month[0:4])
    mon = int(month[5:7])
    return year * 12 + (mon - 1)


def index_to_month(index):
    year, mon = divmod(index, 12)
    return "%04d-%02d" % (year, mon + 1)


def month_of_date(value):
    return "%04d-%02d" % (value.year, value.month)


def month_first_day(month):
    return date(int(month[0:4]), int(month[5:7]), 1)


def next_month_first_day(month):
    return month_first_day(index_to_month(month_index(month) + 1))


def days_in_month(month):
    return (next_month_first_day(month) - month_first_day(month)).days


class Store(object):
    def __init__(self):
        self.programs = {}
        self.agents = {}
        self.merchants = {}
        self.batches = {}
        self.lines = {}
        self.chargebacks = {}
        self.profitability = {}
        self.allocations = {}
        self.statements = {}
        self.adjustments = {}
        self.advances = {}
        self.clock_raw = DEFAULT_CLOCK
        self.clock_dt = parse_instant(DEFAULT_CLOCK)
        self._counter = itertools.count(1)

    def seq(self):
        return next(self._counter)

    # --- logical clock ------------------------------------------------------
    def now(self):
        return self.clock_dt

    def now_iso(self):
        return format_instant(self.clock_dt)

    def today(self):
        return self.clock_dt.date()

    def set_clock(self, raw, parsed):
        self.clock_raw = raw
        self.clock_dt = parsed


db = Store()


def stamp_new(row):
    moment = db.now_iso()
    row["created_at"] = moment
    row["updated_at"] = moment
    row["version"] = 1
    row["_seq"] = db.seq()
    return row


def touch(row):
    """Advance version by exactly 1 and refresh updated_at.

    The logical clock does not tick on its own, so updated_at is stamped as the
    current logical instant offset by one millisecond per mutation already
    applied to the row. A freshly created row therefore has
    created_at == updated_at, while any mutated row has updated_at strictly
    after its created_at, and refused calls change neither.
    """
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = format_instant(
        db.now() + timedelta(milliseconds=row["version"] - 1)
    )
    return row


def ordered(rows):
    """Default list order: created_at ascending, insertion sequence as tiebreak."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
