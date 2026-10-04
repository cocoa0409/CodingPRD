"""In-memory data store and the single server-held logical clock.

Storage is Python dicts keyed by id only — no disk persistence of any kind.
The store starts completely empty on every boot; nothing is seeded.
The logical clock reads exactly 2026-09-01T00:00:00Z until a PlatformAdmin
sets it via POST /drinkware/_clock/set_current_utc; it never falls back to
wall-clock time.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.dealers = {}
        self.applications = {}
        self.cases = {}
        self.product_lines = {}
        self.drops = {}
        self.allocations = {}
        self.orders = {}
        self.proofs = {}
        self.slots = {}
        self.claims = {}


DB = Store()


def get_clock():
    return DB.clock


def set_clock(dt):
    DB.clock = dt
