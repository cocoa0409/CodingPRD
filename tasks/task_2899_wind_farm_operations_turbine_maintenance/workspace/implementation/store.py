"""In-memory store plus the logical clock.

Everything lives in plain Python dicts keyed by id. Nothing is persisted and
nothing is seeded: every row in the system is created through a declared
endpoint.
"""

import itertools
import uuid
from datetime import datetime, timezone

# Before any client advances it the logical clock reads exactly this instant.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "farms",
    "turbine_models",
    "turbines",
    "crews",
    "fault_code_rules",
    "fault_events",
    "weather_windows",
    "work_orders",
    "crane_mobilizations",
    "spare_parts",
    "component_replacements",
    "blade_damages",
    "service_agreements",
    "curtailment_orders",
    "landowner_settlements",
)


def iso(dt):
    """ISO-8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


class Store(object):
    def __init__(self):
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)
        self.tables = {}
        for name in TABLES:
            self.tables[name] = {}

    # ---- logical clock -------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    # ---- row plumbing --------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def new_row(self, **fields):
        row = {
            "id": str(uuid.uuid4()),
            "created_at": self.clock,
            "updated_at": self.clock,
            "version": 1,
        }
        row.update(fields)
        row["_seq"] = self.next_seq()
        return row

    def insert(self, table, row):
        self.tables[table][row["id"]] = row
        return row

    def get(self, table, row_id):
        if not isinstance(row_id, str):
            return None
        return self.tables[table].get(row_id)

    def all(self, table):
        """Every row of a table in insertion-stable created_at order."""
        rows = list(self.tables[table].values())
        rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
        return rows

    def touch(self, row):
        """Refresh updated_at and advance version by exactly 1."""
        row["updated_at"] = self.clock
        row["version"] = row["version"] + 1
        return row

    def apply(self, row, changes):
        """Write changes and bump version only when something really moved.

        Used for pure recomputation cascades (derived projections and
        re-scores) so that a cascade which recomputes a field to the value it
        already held does not advance that row's version.
        """
        dirty = False
        for key, value in changes.items():
            if row.get(key) != value:
                row[key] = value
                dirty = True
        if dirty:
            self.touch(row)
        return dirty


DB = Store()
