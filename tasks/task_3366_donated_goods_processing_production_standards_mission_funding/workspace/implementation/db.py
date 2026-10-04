"""In-memory data store. Starts empty on every boot — no seeding, ever."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.member_orgs = {}
        self.territories = {}
        self.donation_sites = {}
        self.donations = {}
        self.donated_items = {}
        self.production_standards = {}
        self.processing_runs = {}
        self.salvage_lots = {}
        self.mission_programs = {}
        self.funding_allocations = {}
        self.workforce_contracts = {}
        self.milestones = {}
        self.disposal_tickets = {}
        # Monotonic insertion sequence: stable tiebreak for created_at ordering
        # (the logical clock may sit still across many creations).
        self.seq = 0
        # Logical clock: starts at 2026-09-01T00:00:00Z and NEVER falls back
        # to wall-clock time.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def next_seq():
    store.seq += 1
    return store.seq
