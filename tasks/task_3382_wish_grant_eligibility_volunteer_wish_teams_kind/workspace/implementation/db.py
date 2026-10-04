"""In-memory store and logical clock.

The store starts empty on every boot (per-test-server isolation re-launches
the process). The logical clock defaults to 2026-09-01T00:00:00Z and is only
moved by POST /wish-grant/_clock/set_current_utc; wall-clock time is never
consulted for domain timestamps.

tick() mints monotonically increasing timestamps for the bookkeeping spine
(created_at / updated_at) so created_at ordering is deterministic even when
several entities are created at the same logical instant.
"""

import uuid
from datetime import datetime, timezone, timedelta

STORE = {
    "chapters": {},
    "volunteers": {},
    "children": {},
    "referrals": {},
    "wishes": {},
    "teams": {},
    "visits": {},
    "offers": {},
    "plans": {},
    "lines": {},
    "clearances": {},
    "events": {},
}

_CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _CLOCK_DEFAULT
_last_tick = _CLOCK_DEFAULT


def now():
    """The exact logical clock instant (domain 'now')."""
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def tick():
    """A strictly increasing timestamp derived from the logical clock."""
    global _last_tick
    candidate = _last_tick + timedelta(milliseconds=1)
    ts = _clock if _clock > candidate else candidate
    _last_tick = ts
    return ts


def new_id():
    return str(uuid.uuid4())


def new_entity(**fields):
    ts = tick()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    e.update(fields)
    return e


def touch(e):
    e["version"] += 1
    e["updated_at"] = tick()
