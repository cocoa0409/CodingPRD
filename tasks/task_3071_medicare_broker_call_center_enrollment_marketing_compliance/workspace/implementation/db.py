"""In-memory data store.

Nothing is seeded, preloaded or persisted. Every collection starts empty on
every process boot, and every entity any caller needs is created through the
declared API surface. The per-test server isolation re-invokes start.sh, which
replaces the whole module state with a fresh empty store.
"""

import uuid
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Logical clock. Before it is ever set, it reads exactly 2026-09-01T00:00:00Z
# and never falls back to real wall-clock time (PRD 3.1).
# --------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK}

# Each collection is a dict keyed by entity id.
agencies = {}
carriers = {}
agents = {}
state_licenses = {}
appointments = {}
certifications = {}
members = {}
scopes = {}
call_sessions = {}
plans = {}
formulary_drugs = {}
pharmacy_entries = {}
provider_entries = {}
enrollments = {}
ledger_entries = {}
reconciliations = {}
complaints = {}
coaching = {}

# Creation sequences used to break ordering ties by creation order.
_seq = {"value": 0}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["value"] += 1
    return _seq["value"]


def now():
    """The logical clock instant."""
    return _state["clock"]


def set_clock(value):
    _state["clock"] = value


def iso(value):
    """ISO 8601 UTC with three fractional digits, or None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(start, end):
    """Whole days from start to end, half-open (same instant -> 0)."""
    delta = end - start
    return int(delta.total_seconds() // 86400)


def whole_months(start, end):
    """Whole calendar months from start to end (day-of-month aware)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months