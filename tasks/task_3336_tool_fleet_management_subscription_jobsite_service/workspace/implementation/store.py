"""In-memory data store and logical clock.

The store starts EMPTY on every boot. No seeding anywhere. The logical clock
starts at exactly 2026-09-01T00:00:00Z and is advanced only via the
_clock/set_current_utc endpoint; it never falls back to wall-clock time.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone


class Clock:
    """Logical clock with a monotonic tie-breaker so created_at values are
    unique per row even when the logical clock does not advance."""

    START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self._lock = threading.Lock()
        self._now = self.START
        self._seq = 0

    def now(self):
        return self._now

    def advance_to(self, dt):
        """Move the clock forward; returns the previous value (never moves
        backward — a past value simply re-pins to the earlier instant)."""
        with self._lock:
            prev = self._now
            self._now = dt
            return prev

    def stamp(self):
        """Unique creation timestamp: logical clock + a microsecond sequence
        tick so ordering by created_at is stable and unique per row."""
        with self._lock:
            self._seq += 1
            return self._now + timedelta(microseconds=self._seq)


class Store:
    def __init__(self):
        self.clock = Clock()
        self.accounts = {}              # id -> account
        self.rate_cards = {}            # id -> rate card
        self.tool_models = {}           # id -> tool model
        self.agreements = {}            # id -> agreement
        self.assets = {}                # id -> asset
        self.jobsites = {}              # id -> jobsite
        self.usage_events = {}          # id -> usage event
        self.loaner_units = {}          # id -> loaner unit
        self.repair_tickets = {}        # id -> repair ticket
        self.theft_claims = {}          # id -> theft claim
        self.consumable_products = {}   # id -> product
        self.consumable_orders = {}     # id -> order
        self.support_cases = {}         # id -> support case
        self.settlements = {}           # id -> settlement
        self.serial_counters = {}       # tool_model_id -> int
        self.agreement_number_seq = 0
        self.asset_tag_seq = 0

    # ---- id minting ----
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def mint_agreement_number(self):
        self.agreement_number_seq += 1
        return "AGR-%06d" % self.agreement_number_seq

    def mint_serial(self, tool_model_id):
        n = self.serial_counters.get(tool_model_id, 0) + 1
        self.serial_counters[tool_model_id] = n
        return "SN-%s-%05d" % (tool_model_id[:8], n)

    def mint_tag_code(self):
        self.asset_tag_seq += 1
        return "TAG-%07d" % self.asset_tag_seq

    # ---- derived counts ----
    def fleet_size_target(self, agreement):
        return sum(
            1 for a in self.assets.values()
            if a["agreement_id"] == agreement["id"]
            and a["status"] in ("REGISTERED", "DEPLOYED", "IN_TRANSIT", "IN_REPAIR")
        )

    def theft_claim_count(self, agreement):
        return sum(
            1 for c in self.theft_claims.values()
            if self._claim_agreement_id(c) == agreement["id"]
            and c["status"] in ("REPORTED", "POLICE_VERIFIED", "APPROVED")
        )

    def _claim_agreement_id(self, claim):
        asset = self.assets.get(claim["asset_id"])
        return asset["agreement_id"] if asset else None

    def deployed_asset_count(self, jobsite):
        return sum(
            1 for a in self.assets.values()
            if a["current_jobsite_id"] == jobsite["id"] and a["status"] == "DEPLOYED"
        )

    def outstanding_balance(self, account):
        return account.get("outstanding_balance_cents", 0)


store = Store()
