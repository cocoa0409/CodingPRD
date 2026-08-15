"""In-memory data store. Starts empty on every boot — no seeding (per skill contract).

The logical clock (PRD §2.10) defaults to exactly 2026-08-01T00:00:00Z before any
set call and never falls back to wall-clock time.
"""
import threading
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # monotonic creation counter; defines created_at-ascending order
        self.orgs = {}
        self.users = {}
        self.sites = {}
        self.projects = {}
        self.studies = {}
        self.assessments = {}
        self.selections = {}
        self.programs = {}
        self.tests = {}
        self.packages = {}
        self.plans = {}
        self.sessions = {}
        self.guarantees = {}
        self.ledger = {}
        self.logical_clock = DEFAULT_CLOCK

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def children(kind, field, value):
    """All entities of `kind` whose `field` equals `value`, in creation order."""
    return sorted(
        (e for e in getattr(store, kind).values() if e.get(field) == value),
        key=lambda e: e["_seq"],
    )
