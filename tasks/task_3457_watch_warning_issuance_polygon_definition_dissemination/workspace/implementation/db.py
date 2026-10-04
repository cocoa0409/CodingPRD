"""In-memory store + the server-owned logical clock (PRD §2.4).

Storage is Python dicts keyed by id. The store starts empty on every boot;
nothing is seeded. The logical clock starts at exactly 2026-09-01T00:00:00Z
and never falls back to wall-clock.
"""
from datetime import datetime, timezone

STORE = {
    "offices": {},
    "zones": {},
    "agreements": {},
    "channels": {},
    "forecasters": {},
    "storms": {},
    "products": {},
    "coordinations": {},
    "records": {},
    "vevents": {},
    "stats": {},
    "emactions": {},
}

# monotonic creation sequence — tiebreaks list ordering when several resources
# share one logical-clock created_at
_SEQ = {"n": 0}

_CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["now"]


def set_now(value):
    _CLOCK["now"] = value


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]
