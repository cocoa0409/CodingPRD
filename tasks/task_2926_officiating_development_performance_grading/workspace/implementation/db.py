"""In-memory data store and the server-held logical clock.

PRD 2.4: "Time in this system is a server-held value, not a reading of the host
machine's wall clock. ... At server startup the logical clock reads exactly
2026-08-01T00:00:00.000Z; it must never fall back to real wall-clock time."

The store is a set of plain dicts keyed by id. Nothing is seeded at import time
or at boot: every entity is created through a declared endpoint.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        # Collections -- every one starts empty on every boot.
        self.season_programs = {}
        self.officials = {}
        self.applications = {}
        self.field_evaluations = {}
        self.games = {}
        self.assignments = {}
        self.play_grades = {}
        self.appeals = {}
        self.replay_stations = {}
        self.replay_reviews = {}
        self.training_records = {}
        self.season_records = {}
        self.pool_reports = {}
        self.discipline_actions = {}
        # Logical clock (PRD 2.4).
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """PRD 2.6: `id` is a server-minted UUID carrying no type prefix."""
    return str(uuid.uuid4())


def now():
    """The logical clock -- never the wall clock."""
    return db.clock


def set_clock(value):
    db.clock = value


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_row(with_version=True):
    """PRD 2.6 common resource properties."""
    ts = now()
    row = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """PRD 2.6/2.10: any mutation -- including one produced by a cascade --
    refreshes `updated_at` and increases `version` by exactly 1."""
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1
    return row


def order_rows(rows):
    """PRD 2.3: ordered by `created_at` ascending. `_seq` is a stable
    tie-breaker preserving write order when two rows share a clock instant."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _conv(value)
    return out


def _conv(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_conv(v) for v in value]
    return value
