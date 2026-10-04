"""In-memory data store + the logical clock.

The store starts EMPTY on every boot — no seed data of any kind.
All timestamps are derived from the logical clock (the system never reads
the wall clock); startup default is exactly 2026-09-01T00:00:00Z.
"""
from datetime import datetime, timezone

from util import new_id

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# entity tables, keyed by id
db = {
    "customers": {},
    "missions": {},
    "dispenser_ports": {},
    "contracts": {},
    "payloads": {},
    "assignments": {},
    "verifications": {},
    "safety_reviews": {},
    "licenses": {},
    "range_slots": {},
    "exclusion_windows": {},
    "delay_events": {},
    "separation_events": {},
    "anomalies": {},
}

_clock = CLOCK_START
_seq = [0]  # global monotonic creation sequence (tie-breaks equal created_at)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_entity():
    """Base fields for primary resources: id/created_at/updated_at/version."""
    t = now()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def new_append_only():
    """Append-only records (InterfaceVerification, SafetyReview,
    ExclusionWindow, DelayEvent) carry only id and created_at."""
    return {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at on mutation (never bumps version on its own)."""
    entity["updated_at"] = now()


def bump(entity):
    """Documented version increment + updated_at refresh."""
    entity["version"] += 1
    entity["updated_at"] = now()
