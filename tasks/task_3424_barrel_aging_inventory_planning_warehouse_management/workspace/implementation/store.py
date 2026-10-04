"""In-memory data store, logical clock, and identifier/timestamp helpers.

All entity timestamps are logical-clock instants (never wall clock). The
logical clock starts at exactly 2026-09-01T00:00:00Z and is monotonic
non-decreasing. The store starts empty on every boot: no seeding anywhere.
"""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = _DEFAULT_CLOCK


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return _clock


def set_clock(to_dt):
    global _clock
    _clock = to_dt


# ---------------------------------------------------------------------------
# Entity stores (keyed by id). Insertion order is creation order.
# ---------------------------------------------------------------------------

projects = {}
rickhouses = {}
slots = {}
barrels = {}
occupancies = {}
assessments = {}
labels = {}
batches = {}
components = {}
programs = {}
reservations = {}
reports = {}

# Global monotonic sequence: deterministic tie-break for equal logical
# timestamps (creation order) and ledger event ordering.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp formatting / parsing
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
