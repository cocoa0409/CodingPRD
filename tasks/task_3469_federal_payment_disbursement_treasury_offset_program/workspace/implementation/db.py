"""In-memory data store and logical clock.

Storage is Python dicts keyed by id only — no files, no SQLite, no external
persistence. The store starts empty on every process boot; nothing is seeded.

Entities are plain dicts. Internal bookkeeping keys are underscore-prefixed
(currently only "_seq", a monotonic insertion counter used as the deterministic
final ordering tie-break after created_at) and are never serialized.
"""
from constants import DEFAULT_CLOCK_ISO
from util import parse_datetime

STORE = {
    "creditors": {},
    "payees": {},
    "policies": {},
    "debts": {},
    "files": {},
    "payments": {},
    "offsets": {},
    "claims": {},
    "agencies": {},
    "actions": {},
    "reverse_requests": {},
    "agreements": {},
    "dnp_records": {},
}

_CLOCK = {"current": parse_datetime(DEFAULT_CLOCK_ISO)}
_SEQ = {"n": 0}


def clock_now():
    """The single logical clock governing every temporal rule (PRD §2.4)."""
    return _CLOCK["current"]


def set_clock(dt):
    _CLOCK["current"] = dt


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_entity():
    """Fresh common fields (PRD §2.5): created_at/updated_at pinned to the
    logical clock, version starting at 1."""
    now = clock_now()
    return {
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Every mutation bumps version and refreshes updated_at (PRD §2.5),
    including system-driven transitions and cascaded side effects."""
    entity["version"] += 1
    entity["updated_at"] = clock_now()
