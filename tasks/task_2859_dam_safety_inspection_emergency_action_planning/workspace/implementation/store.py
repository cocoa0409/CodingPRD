"""In-memory store and the injectable logical UTC clock.

Every collection starts EMPTY on every boot. Nothing is seeded, preloaded,
registered or hardcoded here: tests build every entity through the declared
API surface, and re-invoking start.sh wipes every byte of state.
"""

import uuid

from common import parse_dt

INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"

ROLES = ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator")


class Store(object):
    def __init__(self):
        self.owners = {}
        self.engineers = {}
        self.reaches = {}
        self.dams = {}
        self.assessments = {}
        self.inspections = {}
        self.deficiencies = {}
        self.orders = {}
        self.plans = {}
        self.exercises = {}
        self.permits = {}
        self.events = {}
        self.readings = {}
        self.drawdowns = {}
        self.ledger = {}
        self._seq = 0
        self.clock = parse_dt(INITIAL_CLOCK_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.clock


def insert(collection, fields, versioned=True):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = db.clock
    row["_seq"] = db.next_seq()
    if versioned:
        row["updated_at"] = db.clock
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row, bump=True):
    row["updated_at"] = db.clock
    if bump and "version" in row:
        row["version"] = row["version"] + 1


def insertion_order(rows):
    """PRD Section 2.3: every collection is ordered by created_at ascending;
    identical created_at values fall back to insertion order, never to id."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def pick_greatest(rows, key):
    """Greatest rows[key]; ties broken by created_at ASC then insertion order."""
    best = None
    for row in rows:
        if best is None:
            best = row
            continue
        if row[key] > best[key]:
            best = row
        elif row[key] == best[key]:
            if row["created_at"] < best["created_at"]:
                best = row
            elif row["created_at"] == best["created_at"] and row["_seq"] < best["_seq"]:
                best = row
    return best


def pick_newest_created(rows):
    """Most recently created row; identical created_at falls back to insertion order."""
    best = None
    for row in rows:
        if best is None:
            best = row
        elif row["created_at"] > best["created_at"]:
            best = row
        elif row["created_at"] == best["created_at"] and row["_seq"] > best["_seq"]:
            best = row
    return best


# ---------------------------------------------------------------------------
# Child-collection accessors
# ---------------------------------------------------------------------------

def by_field(collection, field, value):
    return [r for r in collection.values() if r.get(field) == value]


def dam_deficiencies(dam_id):
    return by_field(db.deficiencies, "dam_id", dam_id)


def dam_plans(dam_id):
    return by_field(db.plans, "dam_id", dam_id)


def dam_inspections(dam_id):
    return by_field(db.inspections, "dam_id", dam_id)


def dam_orders(dam_id):
    return by_field(db.orders, "dam_id", dam_id)


def dam_drawdowns(dam_id):
    return by_field(db.drawdowns, "dam_id", dam_id)


def reach_drawdowns(reach_id):
    return by_field(db.drawdowns, "river_reach_id", reach_id)


def event_drawdowns(event_id):
    return by_field(db.drawdowns, "high_water_event_id", event_id)


def event_readings(event_id):
    return by_field(db.readings, "high_water_event_id", event_id)


def plan_exercises(plan_id):
    return by_field(db.exercises, "eap_id", plan_id)


def owner_entries(owner_id):
    return by_field(db.ledger, "owner_id", owner_id)


def owner_dams(owner_id):
    return by_field(db.dams, "owner_id", owner_id)


def engineer_inspections(engineer_id):
    return by_field(db.inspections, "engineer_id", engineer_id)
