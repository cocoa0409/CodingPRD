"""In-memory data store. Pure module state: a fresh `bash start.sh` wipes every byte."""

import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations[].constants)
# ---------------------------------------------------------------------------
INCOME_CAP_CENTS = 2000000
QUALIFY_SCORE_FLOOR = 620
DTI_QUALIFY_CEILING_BPS = 4500
PREMIUM_INCOME_TIER_CENTS = 1200000
STANDARD_INCOME_TIER_CENTS = 900000
QUALIFICATION_VALID_DAYS = 120
LOCK_BUFFER_DAYS = 45

CAPTURE_RATE_TARGET_DEFAULT_BPS = 8500

PRIORITY_ORDER = ["PRICE_REDUCTION", "CLOSING_COSTS", "RATE_BUYDOWN"]
FREE_EXTENSION_DAYS = 15
MID_TIER_DAYS = 15
MID_TIER_RATE_CENTS_PER_DAY = 45
HIGH_TIER_RATE_CENTS_PER_DAY = 110
RELOCK_FLAT_FEE_CENTS = 120000
MAX_RELOCKS = 2

RECAPTURE_WINDOW_DAYS = 365
CURE_GRACE_DAYS = 3
PARTIAL_FORFEITURE_BPS = 500
TIER_SHIFT_GUARD_CENTS = 500000
PAIR_OFF_FEE_PER_UNIT_CENTS = 95000

MAP_FULL_FORFEITURE_STATES = {"FL", "TX"}
MAP_PARTIAL_FORFEITURE_STATES = {"CA", "NY", "IL"}

ROLES = [
    "Buyer",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
    "PlatformAdmin",
    "Anonymous",
]

# The logical clock never falls back to wall-clock time.
STARTUP_CLOCK = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.communities = {}
        self.forward_commitments = {}
        self.home_sites = {}
        self.buyers = {}
        self.contracts = {}
        self.loan_applications = {}
        self.rate_locks = {}
        self.buydown_records = {}
        self.incentive_allocations = {}
        self.disclosures = {}
        self.deposit_forfeitures = {}
        self.clock = STARTUP_CLOCK
        # (contract_id, lender_entity_code) -> number of expired application rows
        self.expiry_counts = {}
        self.creation_seq = 0

    # -- identity helpers ---------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.creation_seq += 1
        return self.creation_seq


db = Store()


# ---------------------------------------------------------------------------
# Trapezoid helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return format_iso(parse_iso(db.clock))


def clock_dt():
    return parse_iso(db.clock)


def midnight(dt):
    """Truncate an instant to 00:00:00Z of its calendar day (PRD section 2.9)."""
    if dt is None:
        return None
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def day_floor(iso_value):
    if isinstance(iso_value, str):
        iso_value = parse_iso(iso_value)
    return format_iso(midnight(iso_value))


def plus_days(iso_value, days):
    """date-plus-days: truncate the start instant to midnight, then add whole days."""
    if isinstance(iso_value, str):
        iso_value = parse_iso(iso_value)
    return format_iso(midnight(iso_value) + timedelta(days=days))


def add_days_from_clock(days):
    return format_iso(clock_dt() + timedelta(days=days))


def iso_ge(left, right):
    a, b = parse_iso(left), parse_iso(right)
    if a is None or b is None:
        return False
    return a >= b


def iso_gt(left, right):
    a, b = parse_iso(left), parse_iso(right)
    if a is None or b is None:
        return False
    return a > b


def iso_le(left, right):
    a, b = parse_iso(left), parse_iso(right)
    if a is None or b is None:
        return False
    return a <= b