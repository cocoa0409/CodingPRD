"""In-memory data store, id/timestamp helpers, and the logical clock.

The store starts completely empty on every boot; tests build all state via
the declared API surface. Underscore-prefixed keys on entity dicts are
internal (never serialized).
"""
import itertools
import re
import uuid
from datetime import datetime, timezone

# --- entity stores -----------------------------------------------------------
BRANDS = {}
MARKETS = {}
BROKERAGES = {}
AGREEMENTS = {}
PLANS = {}
AGENTS = {}
AC_REPORTS = {}
GCI_REPORTS = {}
PERIODS = {}
DEFAULTS = {}
LEDGER = []  # append-only list of AdFundLedgerEntry dicts
COUNCILS = {}
PROPOSALS = {}
AUDITS = {}
TASKS = {}

_seq = itertools.count(1)

# --- logical clock (PRD 2.7): starts exactly 2026-09-01T00:00:00Z ------------
CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = CLOCK_DEFAULT


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def wall_now():
    return datetime.now(timezone.utc)


def wall_now_iso():
    return iso_ms(wall_now())


def logical_now():
    return _clock


def logical_now_iso():
    return iso_ms(_clock)


def get_logical_clock():
    return _clock


def set_logical_clock(dt):
    global _clock
    _clock = dt


_DATE_ONLY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def parse_iso(value):
    """Parse an ISO8601 date or datetime to an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if _DATE_ONLY.match(s):
            return datetime.strptime(s, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        s2 = s[:-1] + '+00:00' if s.endswith('Z') else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None
