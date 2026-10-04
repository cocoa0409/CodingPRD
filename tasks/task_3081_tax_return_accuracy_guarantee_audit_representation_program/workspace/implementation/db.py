"""In-memory data store for the Tax Return Accuracy Guarantee program.

The store starts empty on every boot — no seeding. All entities are
constructed through the API surface.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

_logical_clock = None  # datetime, lazily initialised to _CLOCK_DEFAULT


def _parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Return the current logical clock (aware UTC datetime)."""
    global _logical_clock
    if _logical_clock is None:
        _logical_clock = _parse_iso(_CLOCK_DEFAULT)
    return _logical_clock


def set_clock(to_iso8601):
    global _logical_clock
    _logical_clock = _parse_iso(to_iso8601)
    return _logical_clock


def now_iso():
    """Current logical clock as ISO8601 UTC with millisecond precision."""
    dt = clock_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_iso(dt):
    """Format an aware datetime as ISO8601 UTC with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

offices = {}            # id -> dict
preparers = {}          # id -> dict
clients = {}            # id -> dict
returns = {}            # id -> dict
products = {}           # id -> dict
notices = {}            # id -> dict
claims = {}             # id -> dict
agents = {}             # id -> dict
assignments = {}        # id -> dict
poas = {}               # id -> dict
remediations = {}       # id -> dict
escrows = {}            # id -> dict
snapshots = {}          # id -> dict


def new_id():
    return str(uuid.uuid4())


def base_record():
    """Common system fields for a fresh resource."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }


def touch(rec):
    """Mutation hook: refresh updated_at and bump version."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
