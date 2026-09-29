"""In-memory store, logical clock and row bookkeeping.

The store starts empty on every boot: nothing is seeded, preloaded or
hardcoded. Every row is created by an API caller.
"""

import threading
import uuid

import constants
from util import parse_iso

_LOCK = threading.RLock()

COLLECTIONS = (
    "producers",
    "training_courses",
    "course_enrollments",
    "series",
    "programs",
    "attestations",
    "channels",
    "playback_slots",
    "studio_resources",
    "reservations",
    "damage_assessments",
    "crew_assignments",
    "funding_periods",
    "archive_assets",
)

# collection name -> dict of id -> row (insertion ordered)
store = {name: {} for name in COLLECTIONS}

# the single logical UTC instant (PRD 2.5)
_clock = {"now": parse_iso(constants.DEFAULT_CLOCK_UTC)}

# centre-wide monotone counter for Series.sequence_number (PRD 3.2)
_counters = {"series_sequence": 0}


def lock():
    return _LOCK


def now():
    """The current logical UTC instant."""
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt
    return _clock["now"]


def new_id():
    return str(uuid.uuid4())


def next_series_sequence():
    _counters["series_sequence"] += 1
    return _counters["series_sequence"]


def insert(collection, row):
    store[collection][row["id"]] = row
    return row


def get(collection, ident):
    if not isinstance(ident, str):
        return None
    return store[collection].get(ident)


def all_rows(collection):
    return list(store[collection].values())


def new_row(collection, fields):
    """Create a row carrying the common system fields (PRD 2.4)."""
    instant = now()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = instant
    if collection != "attestations":
        row["updated_at"] = instant
        row["version"] = 1
    row["_collection"] = collection
    return insert(collection, row)


def bump(row):
    """Mutation bookkeeping (PRD 2.4 / 2.9).

    A row's ``version`` increments by exactly 1 for the mutation and its
    ``updated_at`` refreshes -- including when a cascade rather than the caller
    reached it. A single request counts as a single mutation of a given row, so
    a row reached twice inside one request still advances by exactly 1.
    Attestations carry neither field and are never bumped.
    """
    if row is None:
        return row
    if "version" not in row:
        return row
    touched = _touched_set()
    if touched is not None:
        if row["id"] in touched:
            return row
        touched.add(row["id"])
    row["updated_at"] = now()
    row["version"] = row["version"] + 1
    return row


def _touched_set():
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return None
        if not hasattr(g, "_touched_rows"):
            g._touched_rows = set()
        return g._touched_rows
    except Exception:
        return None
