"""In-memory data store.

Every collection is a plain dict keyed by the row's UUID id.  The store is
created empty on every boot and nothing is ever seeded: all rows arrive through
the declared API surface.
"""

import util


class Store(object):
    def __init__(self):
        self.zones = {}
        self.zone_assessments = {}
        self.fire_incidents = {}
        self.households = {}
        self.crews = {}
        self.routes = {}
        self.visits = {}
        self.device_lots = {}
        self.installations = {}
        self.partners = {}
        self.grants = {}
        self.grant_reports = {}
        self.escape_plans = {}
        self.follow_ups = {}
        self._counter = 0

    def next_seq(self):
        """Monotonic insertion sequence.  The logical clock does not advance on
        its own, so rows created in one test share a created_at; this keeps the
        created_at-ascending default ordering of PRD 2.3 stable."""
        self._counter += 1
        return self._counter


store = Store()


def stamp_new(row):
    """Apply the four common system fields of PRD 2.6."""
    now = util.clock.now()
    row["id"] = util.new_id()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def stamp_event(row):
    """Append-only children carry only id and created_at (PRD 2.6)."""
    row["id"] = util.new_id()
    row["created_at"] = util.clock.now()
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    """PRD 2.6: every mutation refreshes updated_at and increments version by 1."""
    row["updated_at"] = util.clock.now()
    row["version"] = row["version"] + 1
    return row


def by_created_at(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
