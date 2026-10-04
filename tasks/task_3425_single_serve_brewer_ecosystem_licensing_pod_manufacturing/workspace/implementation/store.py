"""In-memory data store and the logical clock.

The store starts empty on every boot — no seeding. The logical clock starts at
exactly 2026-09-01T00:00:00Z (fixed startup default, never wall-clock).
"""
import itertools
from datetime import datetime, timezone

db = {
    "brands": {},
    "agreements": {},
    "audits": {},
    "varieties": {},
    "models": {},
    "facilities": {},
    "lines": {},
    "runs": {},
    "households": {},
    "brewers": {},
    "consumption": {},
    "events": {},
    "accounts": {},
    "plans": {},
    "statements": {},
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


_STARTUP_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _STARTUP_CLOCK}


def get_clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
