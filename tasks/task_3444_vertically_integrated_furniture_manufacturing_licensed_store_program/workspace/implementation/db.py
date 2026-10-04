"""In-memory data store + logical clock. Starts empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone

from constants import CLOCK_START


class Store:
    def __init__(self):
        self.factories = {}
        self.product_lines = {}
        self.licensees = {}
        self.territories = {}
        self.retail_accounts = {}
        self.dcs = {}
        self.cycles = {}
        self.orders = {}
        self.appointments = {}
        self.claims = {}
        self.parts_orders = {}
        # Monotonic creation counter: chronological tie-break when created_at ties.
        self.seq = 0
        # Logical clock (PRD §2.5): starts at exactly 2026-09-01T00:00:00Z.
        self.clock = datetime(*CLOCK_START, tzinfo=timezone.utc)
        # licensee_id -> list of instantaneous cycle scores (oldest..newest Decimals)
        self.score_history = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
LOCK = threading.RLock()
