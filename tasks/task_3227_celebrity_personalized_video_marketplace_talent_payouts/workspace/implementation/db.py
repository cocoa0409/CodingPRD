"""In-memory data store and logical clock.

Storage is plain Python dicts keyed by id. Nothing is persisted to disk and
nothing is seeded at startup — every boot begins completely empty, so a fresh
process (per-test-server restart) wipes every byte of state.
"""
import uuid
from datetime import datetime, timedelta, timezone

EPOCH = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock = {"now": EPOCH}


def clock_now():
    return _clock["now"]


def set_clock(to_dt):
    _clock["now"] = to_dt


# ---------------------------------------------------------------------------
# Stores (empty at boot; no seeding)
# ---------------------------------------------------------------------------
talents = {}
buyers = {}
orders = {}
videos = {}
rerecord_requests = {}
license_grants = {}
payout_lines = {}
payouts = {}
tax_documents = {}
disputes = {}


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO-8601 UTC timestamp with three fractional digits, 'Z' suffix."""
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    ms = "%03d" % (dt.microsecond // 1000)
    return s + ms + "Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime string; return None if malformed."""
    if not isinstance(value, str):
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def hours(dt, h):
    return dt + timedelta(hours=h)


def days(dt, d):
    return dt + timedelta(days=d)
