"""In-memory data store and the server-side logical clock.

The store starts EMPTY on every boot — no seeding, no preloading. Every entity
is created through the declared API surface. The logical clock starts at
exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time.
"""
import itertools
from datetime import datetime, timezone

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"


def _parse_iso(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# entity collections, keyed by id; dicts preserve insertion order
db = {
    "distributors": {},
    "territories": {},
    "accounts": {},
    "products": {},
    "authorizations": {},
    "orders": {},
    "order_lines": {},
    "plants": {},
    "runs": {},
    "lots": {},
    "deliveries": {},
    "visits": {},
    "slicers": {},
    "logs": {},
    "certs": {},
    "promos": {},
    "incidents": {},
}

# global insertion sequence — stable tiebreaker when created_at values tie
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


_clock_now = _parse_iso(CLOCK_DEFAULT_ISO)


def now():
    """Current logical time (timezone-aware UTC)."""
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt
