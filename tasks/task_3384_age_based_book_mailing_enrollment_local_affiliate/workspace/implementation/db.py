"""In-memory data store plus the logical clock.

The store starts completely empty on every boot; nothing is seeded.
Records are plain dicts. Keys starting with "_" are internal-only and are
stripped at serialization time (e.g. _seq insertion order, parsed dates).
"""

import itertools
import uuid
from datetime import datetime, timezone

state_programs = {}
affiliates = {}
agreements = {}
population_stats = {}
children = {}
address_changes = {}
titles = {}
selections = {}
print_orders = {}
waves = {}
items = {}
invoices = {}

_seq = itertools.count(1)

# Logical clock: starts at exactly 2026-09-01T00:00:00Z and only ever moves
# via POST /library/_clock/set_current_utc. Never falls back to wall clock.
_clock = {"current": datetime(2026, 9, 1, tzinfo=timezone.utc)}


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def get_clock():
    return _clock["current"]


def set_clock(dt):
    _clock["current"] = dt


def logical_month():
    c = _clock["current"]
    return "%04d-%02d" % (c.year, c.month)


def logical_date():
    return _clock["current"].date()


def stamp(dt=None):
    """ISO 8601 UTC timestamp with three fractional digits (logical clock)."""
    c = dt or _clock["current"]
    return c.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (c.microsecond // 1000)


def base_record():
    ts = stamp()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Mark a record as modified: bump version and refresh updated_at."""
    rec["version"] += 1
    rec["updated_at"] = stamp()
