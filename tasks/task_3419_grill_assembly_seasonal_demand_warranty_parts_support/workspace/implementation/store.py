"""In-memory data store. Pure Python dicts keyed by id; fresh boot = empty state.
No seeding, no persistence, no file cache. `db` is module-level and a fresh
process re-imports this module, so every start.sh launch begins empty."""

import uuid

import clock


class DB:
    def __init__(self):
        self.seasons = {}
        self.models = {}
        self.channels = {}
        self.lots = {}
        self.allocations = {}
        self.assemblers = {}
        self.jobs = {}
        self.sales = {}
        self.claims = {}
        self.parts = {}
        self.parts_orders = {}
        self.devices = {}
        self.seq = 0  # global monotonic insertion counter (deterministic tie-breaks)


db = DB()


def next_seq():
    db.seq += 1
    return db.seq


def new_entity(fields):
    """Stamp the common system fields (PRD §2.5): id, created_at, updated_at,
    version=1, plus an internal insertion sequence (never serialized)."""
    ts = clock.iso_ms(clock.now())
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    entity.update(fields)
    return entity


def touch(entity):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    entity["updated_at"] = clock.iso_ms(clock.now())
    entity["version"] += 1


def find(collection, entity_id):
    return collection.get(entity_id)
