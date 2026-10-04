"""In-memory data store and logical clock for the Heavy Truck Uptime API.

The store starts empty on every boot; nothing is seeded.
"""

from datetime import datetime, timezone, timedelta
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.fleets = {}              # id -> dict
        self.trucks = {}              # id -> dict
        self.dealers = {}             # id -> dict
        self.bays = {}                # id -> dict
        self.fault_events = {}        # id -> dict
        self.cases = {}               # id -> dict
        self.work_orders = {}         # id -> dict
        self.part_orders = {}         # id -> dict
        self.claims = {}              # id -> dict
        self.part_returns = {}        # id -> dict
        self.recoveries = {}          # id -> dict
        self.coverage_contracts = {}  # id -> dict
        self.campaigns = {}           # id -> dict
        self.campaign_completions = {}  # id -> dict
        self.reliability_reports = {}  # id -> dict
        self.ops_run_index = 0
        # Logical clock starts at 2026-09-01T00:00:00Z
        self.clock = datetime(2026, 9, 1, tzinfo=timezone.utc)
        # Event history for reliability recompute-from-scratch audit.
        # Each entry: (fleet_id, penalty_kind, amount)
        self.reliability_events = []
        # Idempotency ledger for repeat-repair penalty per (truck_id, fault_code)
        self.repeat_penalized = set()

    def now(self):
        return self.clock


db = Store()
