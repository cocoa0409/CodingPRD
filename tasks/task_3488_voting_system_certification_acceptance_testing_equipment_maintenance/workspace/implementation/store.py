"""In-memory data store and logical clock.

The store is module-level and starts empty on every process boot. No seeding,
no external persistence: all state arrives via API calls (per-task contract).
"""
import threading
from datetime import datetime, timezone

# Logical clock boot value (PRD section 2.4): fixed, never wall-clock.
BOOT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.voting_systems = {}
        self.test_laboratories = {}
        self.certification_campaigns = {}
        self.certificates = {}
        self.jurisdictions = {}
        self.election_officials = {}
        self.procurements = {}
        self.acceptance_tests = {}
        self.election_definitions = {}
        self.logic_accuracy_tests = {}
        self.equipment_units = {}
        self.maintenance_work_orders = {}
        self.custody_transfers = {}
        self.software_modifications = {}
        self.post_election_audits = {}
        # Logical clock (settable only via POST /_clock/set_current_utc).
        self.clock = BOOT_CLOCK
        # Monotonic insertion sequence for stable list ordering on timestamp ties.
        self.seq = 0
        self.lock = threading.RLock()


db = Store()
