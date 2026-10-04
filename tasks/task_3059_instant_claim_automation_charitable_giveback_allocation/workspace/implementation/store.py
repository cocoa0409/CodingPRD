"""In-memory data store + logical clock + helpers."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_utc = CLOCK_START


def now():
    return _current_utc


def set_clock(dt):
    global _current_utc
    _current_utc = dt


def fmt_ts(dt):
    """ISO8601 UTC with 3 fractional digits, trailing Z."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(s):
    """Parse an ISO8601 timestamp (accepts trailing Z or offset)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Stores: dict of id -> dict
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.rate_filings = {}
        self.fee_configs = {}
        self.treaties = {}
        self.causes = {}
        self.cohorts = {}
        self.policyholders = {}
        self.quotes = {}
        self.applications = {}
        self.policies = {}
        self.claims = {}
        self.payments = {}
        self.ledger = {}
        self.appeals = {}
        self.cohort_treaty = {}  # cohort_id -> treaty_id


db = DB()


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Money rounding
# ---------------------------------------------------------------------------
def rhu(amount):
    """Round-half-up a Decimal/number to integer cents."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x):
    return Decimal(str(x))
