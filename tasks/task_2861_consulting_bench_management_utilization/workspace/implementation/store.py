"""In-memory store, id/timestamp minting and the server-held logical clock.

Every collection starts empty on boot: nothing in this module (or anywhere else
in the implementation) seeds, preloads or hardcodes an entity. Tests build all
state through the declared endpoints.
"""
import uuid
from datetime import datetime, timedelta

from flask import g

from helpers import UTC

COLLECTIONS = (
    "practice_groups",
    "skills",
    "consultants",
    "skill_assertions",
    "demand_opportunities",
    "assignments",
    "bench_spells",
    "reskilling_programs",
    "subcontractor_firms",
    "external_placements",
    "discount_approvals",
    "utilization_periods",
    "hiring_forecasts",
)

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.data = {name: {} for name in COLLECTIONS}
        self.clock = CLOCK_EPOCH
        self._seq = 0
        self._last_stamp = None

    # -- collections ----------------------------------------------------
    def table(self, name):
        return self.data[name]

    def get(self, name, row_id):
        if not isinstance(row_id, str):
            return None
        return self.data[name].get(row_id)

    def all(self, name):
        return sorted(self.data[name].values(), key=lambda row: row["_seq"])

    # -- minting --------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def stamp(self):
        moment = datetime.now(UTC)
        if self._last_stamp is not None and moment <= self._last_stamp:
            moment = self._last_stamp + timedelta(milliseconds=1)
        self._last_stamp = moment
        return moment

    def new_row(self, name, versioned=True):
        moment = self.stamp()
        row = {
            "id": str(uuid.uuid4()),
            "created_at": moment,
            "_seq": self.next_seq(),
            "_kind": name,
        }
        if versioned:
            row["updated_at"] = moment
            row["version"] = 1
        return row

    def insert(self, name, row):
        self.data[name][row["id"]] = row
        return row

    # -- clock ----------------------------------------------------------
    def clock_date(self):
        return self.clock.date()


db = Store()


def bump(row):
    """Mutation bookkeeping: one version increment per row per request, so a
    cascade that touches the same row twice still reports a single increment."""
    if row is None or "version" not in row:
        return row
    touched = getattr(g, "_bumped", None)
    if touched is None:
        touched = set()
        g._bumped = touched
    if row["id"] in touched:
        return row
    touched.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = db.stamp()
    return row
