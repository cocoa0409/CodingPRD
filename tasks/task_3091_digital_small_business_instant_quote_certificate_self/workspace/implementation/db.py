"""In-memory data store, logical clock, id/timestamp/day helpers.

The store starts empty on every boot. No seeding of any kind.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_EPOCH_DAY = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = _CLOCK_START


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
    return _clock


def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def day_of(dt):
    """Whole UTC civil days since 2026-01-01T00:00:00Z (instant floors to its day)."""
    dt = dt.astimezone(timezone.utc)
    floored = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return (floored - _EPOCH_DAY).days


def day_start(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def day_end(dt):
    return day_start(dt) + timedelta(days=1) - timedelta(milliseconds=1)


# ---------------------------------------------------------------------------
# Id / sequence
# ---------------------------------------------------------------------------
_seq = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Stores: dict keyed by id. Everything starts empty.
# ---------------------------------------------------------------------------
appetite_rules = {}
class_codes = {}
business_accounts = {}
risk_signals = {}
quotes = {}
policies = {}
endorsements = {}
certificates = {}
claims = {}
claim_evidence = {}
referrals = {}
non_renewal_notices = {}
audit_events = {}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    """Lowercase word tokens, punctuation stripped; tokens longer than 64
    chars do not participate."""
    tokens = _TOKEN_RE.findall(text.lower())
    return set(t for t in tokens if len(t) <= 64)
