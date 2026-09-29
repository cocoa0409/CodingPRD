"""In-memory storage.

Everything lives in plain dicts inside this process. There is no database file, no
cache directory and no seeding: a fresh process starts with every collection empty
and the logical clock at its mandated default.
"""

from flask import g

import util
from constants import DEFAULT_CLOCK

COLLECTIONS = (
    "operators",
    "aircraft",
    "pilots",
    "policies",
    "schedules",
    "endorsements",
    "markets",
    "placements",
    "claims",
    "assessments",
    "transactions",
    "declarations",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = util.parse_instant(DEFAULT_CLOCK)
        self._seq = 0
        self._policy_counter = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_policy_number(self):
        self._policy_counter += 1
        return "AVN-%06d" % self._policy_counter


db = Store()


def sort_key(rec):
    """Deterministic created_at ascending order, insertion sequence breaking ties."""
    return (rec["created_at"], rec["_seq"])


def ordered(collection):
    return sorted(collection.values(), key=sort_key)


def new_record(collection, fields, versioned=True):
    """Create a row with the common properties of PRD 2.4 and store it."""
    rec = {
        "id": util.new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
    }
    if versioned:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    rec.update(fields)
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Advance version once per row per request and refresh updated_at."""
    if "version" not in rec:
        return rec
    try:
        touched = g._touched
    except (AttributeError, RuntimeError):
        touched = None
    if touched is None:
        touched = set()
        try:
            g._touched = touched
        except RuntimeError:
            pass
    key = id(rec)
    rec["updated_at"] = db.clock
    if key not in touched:
        touched.add(key)
        rec["version"] = rec.get("version", 1) + 1
    return rec
