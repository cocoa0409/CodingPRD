"""In-memory data store and the logical program clock (PRD section 2.5).

Storage is in-memory only: plain dicts keyed by id. Nothing is seeded at
startup — every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

STORES = {
    "zones": {},
    "pitches": {},
    "performers": {},
    "applications": {},
    "auditions": {},
    "audition_scores": {},
    "permits": {},
    "invoices": {},
    "draws": {},
    "entries": {},
    "bookings": {},
    "readings": {},
    "complaints": {},
    "closures": {},
}

# Monotonic insertion sequence: a stable tie-breaker when several rows share
# one created_at (the logical clock does not move on its own).
_seq = itertools.count(1)

# Per-season permit placard sequence: BP-<season_year>-<0001>.
_permit_seq = {}

# The logical UTC clock. It starts at exactly 2026-08-01T00:00:00Z when the
# process boots and never falls back to the host's wall-clock time.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


def set_now(dt):
    previous = CLOCK["now"]
    CLOCK["now"] = dt
    return previous


def next_seq():
    return next(_seq)


def next_permit_number(season_year):
    nxt = _permit_seq.get(season_year, 0) + 1
    _permit_seq[season_year] = nxt
    return "BP-%d-%04d" % (season_year, nxt)


def new_id():
    return str(uuid.uuid4())


def get(store, ident):
    if not isinstance(ident, str):
        return None
    return STORES[store].get(ident)


def all_of(store):
    return list(STORES[store].values())
