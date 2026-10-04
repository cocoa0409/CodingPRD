"""In-memory data store + logical clock.

The store starts empty on every boot (per-test-server isolation restarts the
process via start.sh). No entity is ever seeded at startup.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4): default exactly 2026-09-01T00:00:00Z.
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    """Current logical time (datetime, tz-aware UTC)."""
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt.astimezone(timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 timestamp to a tz-aware UTC datetime.

    Returns None when unparseable (caller maps to ERR_INVALID_REQUEST).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_ts(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Entity stores: plain dicts keyed by id. Values are dicts; keys starting with
# "_" are private (never serialized).
# ---------------------------------------------------------------------------
offices = {}
investigations = {}
participations = {}
demands = {}
responses = {}
settlements = {}
lines = {}
disbursements = {}
claimants = {}
periods = {}

# settlement_id -> list of state_office_ids ACTIVE at open-sign-on time
eligible_snapshots = {}

_seq = itertools.count(1)
_lead_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def next_lead_seq():
    return next(_lead_seq)


def new_id():
    return str(uuid.uuid4())


def new_entity(kind_store):
    """Create the base record (common fields) and register it in the store."""
    ent = {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    kind_store[ent["id"]] = ent
    return ent


def touch(ent):
    """Refresh updated_at and bump version exactly once per mutation."""
    ent["updated_at"] = now()
    ent["version"] += 1
