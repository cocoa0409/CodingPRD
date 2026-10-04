"""In-memory data store, the server-held logical clock, and common fields.

Storage is plain dicts keyed by id (PRD build contract: in-memory only, no
seeding). The logical clock starts at exactly 2026-09-01T00:00:00Z and is the
only time source consulted by business rules (PRD section 2.5).
"""
import uuid
from datetime import datetime, timedelta, timezone

from timeutil import fmt_wall

STORE = {
    "suppliers": {},
    "commitments": {},
    "certifications": {},
    "audits": {},
    "enrollments": {},
    "payments": {},
    "flavors": {},
    "revival_requests": {},
    "slots": {},
    "campaigns": {},
    "shops": {},
    "orders": {},
}

LOGICAL_CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}

_seq = [0]
_last_ts = [None]


def new_id():
    """UUID with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


def _tick_ts():
    """Strictly increasing wall-clock timestamp string (3 fractional digits)."""
    n = datetime.now(timezone.utc)
    last = _last_ts[0]
    if last is not None and n <= last:
        n = last + timedelta(milliseconds=1)
    _last_ts[0] = n
    return fmt_wall(n)


def new_resource():
    """Common system-managed fields for a fresh resource (PRD section 2.4)."""
    ts = _tick_ts()
    _seq[0] += 1
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _seq[0],
    }


def touch(res):
    """Register a mutation: refresh updated_at and bump version by exactly 1."""
    res["updated_at"] = _tick_ts()
    res["version"] = res.get("version", 1) + 1


def public(res):
    """Strip internal bookkeeping keys (underscore-prefixed) for output."""
    return {k: v for k, v in res.items() if not k.startswith("_")}


def sorted_items(items):
    """Default list order: created_at ascending, oldest first (PRD 2.3).

    The monotonic creation sequence is equivalent to created_at order.
    """
    return sorted(items, key=lambda r: r["_seq"])
