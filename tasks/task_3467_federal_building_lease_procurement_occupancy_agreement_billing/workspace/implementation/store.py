"""In-memory data store, logical clock, entity lifecycle helpers.

Storage is dicts keyed by id. Every boot starts empty: no seeding, no
preload, no on-disk persistence. The logical clock defaults to exactly
2026-09-01T00:00:00Z and never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

DB = {
    "agencies": {},
    "buildings": {},
    "requirements": {},
    "offers": {},
    "leases": {},
    "plans": {},
    "oas": {},
    "bills": {},
    "alterations": {},
    "tickets": {},
    "surveys": {},
    "reductions": {},
}

_INITIAL_CLOCK = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


# The logical clock: raw echo string + parsed instant.
CLOCK = {"raw": _INITIAL_CLOCK, "dt": _parse_iso(_INITIAL_CLOCK)}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return CLOCK["dt"]


def now_str():
    """Logical clock instant formatted with 3 fractional digits, Z suffix."""
    d = CLOCK["dt"]
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def set_clock(raw, dt):
    CLOCK["raw"] = raw
    CLOCK["dt"] = dt


def make_entity():
    """New entity skeleton: id, common fields at version 1."""
    ts = now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(e):
    """Every mutation (incl. system transitions, cascades, recomputation)
    increments version and refreshes updated_at."""
    e["version"] += 1
    e["updated_at"] = now_str()


def _pub_val(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _pub_val(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_pub_val(x) for x in v]
    return v


def pub(e):
    """Public serialization: drop internal (underscore-prefixed) keys."""
    return {k: _pub_val(v) for k, v in e.items() if not k.startswith("_")}


def sorted_items(coll):
    """List ordering: created_at ascending, creation sequence as tiebreak."""
    return sorted(coll, key=lambda e: (e["created_at"], e["_seq"]))
