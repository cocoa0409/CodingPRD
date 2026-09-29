"""In-memory data store and the server-owned logical clock.

Storage is process-local Python dicts keyed by id. The store starts completely
empty on every boot: nothing is seeded, preloaded or hardcoded. Every entity is
created by callers through the declared endpoints.
"""
import threading

from util import iso, new_id, parse_dt, real_now_iso, sort_rows

# --- constants (SCAFFOLD calculations) ---------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"

PSI_REQUEST_TTL_HOURS = 72
PSI_FEE_STANDARD_CENTS = 12500
PSI_FEE_PREMIUM_CENTS = 27500

ROUND_RESPONSE_HOURS = 48
ROUND_COOLDOWN_HOURS = 2
MAX_NEGOTIATION_ROUNDS = 3
INTAKE_GRACE_HOURS = 48
DEFAULT_SELLER_RESPONSE_HOURS = 24

TRANSPORT_DISPATCH_FEE_CENTS = 8500
TRANSPORT_TIER1_MILES = 100
TRANSPORT_TIER1_CENTS_PER_MILE = 185
TRANSPORT_TIER2_MILES = 400
TRANSPORT_TIER2_CENTS_PER_MILE = 155
TRANSPORT_TIER3_CENTS_PER_MILE = 130

SEVERITY_MULTIPLIER_BPS = {"GREEN": 10000, "YELLOW": 8500, "RED": 6000}
MILEAGE_DIMINUTION_CENTS_PER_MILE = 45

SCORECARD_WINDOW_DAYS = 90
MIN_SCORECARD_SALES = 4
TIER_WATCH_BPS = 800
TIER_PROBATION_BPS = 1500
TIER_BLOCK_BPS = 2500

FRIVOLOUS_FEE_BASE_CENTS = 25000
FRIVOLOUS_FEE_CAP_CENTS = 60000
FRIVOLOUS_SUSPENSION_COUNT = 3

# --- enums -------------------------------------------------------------------
ROLES = ["AuctionAdmin", "BlockClerk", "Arbitrator", "Inspector", "BuyerRep", "SellerRep"]
DEFECT_CLASSES = ["FRAME_DAMAGE", "MECHANICAL", "MILEAGE_DISCREPANCY", "TITLE_BRANDED", "TITLE_MISSING"]
TITLE_DEFECT_CLASSES = ["TITLE_BRANDED", "TITLE_MISSING"]
LIGHT_CHANNELS = ["GREEN", "YELLOW", "RED"]
TITLE_STATUSES = ["CLEAN", "BRANDED_SALVAGE", "MISSING"]
SETTLEMENT_STATUSES = ["UNSETTLED", "SETTLED", "REVERSED"]
ARBITRATION_STATUSES = ["NONE", "ACTIVE", "RESOLVED"]
PROGRAM_TIERS = ["STANDARD", "PREMIUM"]
PSI_STATUSES = ["REQUESTED", "COMPLETED", "EXPIRED"]
CASE_STATUSES = [
    "SUBMITTED", "UNDER_REVIEW", "NEGOTIATION", "COUNTERED", "ARBITRATOR_REVIEW",
    "RESOLVED_ALLOWANCE", "UNWOUND", "DENIED", "WITHDRAWN", "EXPIRED",
]
TERMINAL_CASE_STATUSES = ["RESOLVED_ALLOWANCE", "UNWOUND", "DENIED", "WITHDRAWN", "EXPIRED"]
NON_TERMINAL_CASE_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "NEGOTIATION", "COUNTERED", "ARBITRATOR_REVIEW"]
EVIDENCE_TYPES = ["INSPECTION_REPORT", "DIAGNOSTIC_SCAN", "THIRD_PARTY_VERIFICATION", "PHOTO_SET", "TITLE_DOCUMENT"]
VERIFIED_EVIDENCE_TYPES = ["INSPECTION_REPORT", "THIRD_PARTY_VERIFICATION"]
RESPONSE_TYPES = ["OFFER_REPAIR_ALLOWANCE", "DISPUTE", "ACCEPT_UNWIND", "TIMEOUT"]
CLIENT_RESPONSE_TYPES = ["OFFER_REPAIR_ALLOWANCE", "DISPUTE", "ACCEPT_UNWIND"]
ROUND_STATUSES = ["OPEN", "COUNTERED", "ACCEPTED", "SUPERSEDED", "EXPIRED", "CLOSED"]
LEG_TYPES = ["INBOUND_TO_AUCTION", "RETURN_TO_SELLER", "TO_BUYER_REDELIVERY"]
OUTCOMES = ["UNWIND", "REPAIR_ALLOWANCE", "CLAIM_DENIED", "FRIVOLOUS_DENIED"]
UPHELD_OUTCOMES = ["UNWIND", "REPAIR_ALLOWANCE"]
ALLOWANCE_VARIANTS = ["NEGOTIATED_ACCEPT", "ARBITRATOR_AWARD", "NONE"]
FAULT_PARTIES = ["SELLER", "BUYER", "NONE"]
POLICY_TIERS = ["GOOD_STANDING", "WATCH", "PROBATION", "BLOCKED"]
PRIVILEGE_STATUSES = ["ACTIVE", "FEE_HOLD", "SUSPENDED"]
LEDGER_PARTIES = ["BUYER", "SELLER", "AUCTION"]
LEDGER_ENTRY_TYPES = [
    "SALE_PROCEEDS", "SALE_PROCEEDS_REVERSAL", "TRANSPORT_ALLOCATION",
    "REPAIR_ALLOWANCE", "FRIVOLOUS_FEE_ASSESSED", "FRIVOLOUS_FEE_OFFSET",
]
ACTION_TYPES = ["WATCH_LIST", "PROBATION", "BLOCK", "REINSTATE"]

TIER_TO_ACTION_TYPE = {"WATCH": "WATCH_LIST", "PROBATION": "PROBATION", "BLOCKED": "BLOCK"}

COLLECTIONS = [
    "sellers", "buyers", "policies", "sales", "announcements", "inspections",
    "cases", "evidence", "rounds", "legs", "decisions", "ledger", "fees",
    "policy_actions",
]


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = parse_dt(CLOCK_STARTUP_DEFAULT)

    # --- logical clock ------------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return iso(self.clock)

    # --- insertion ---------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def insert(self, collection, row, mutable):
        row["id"] = new_id()
        row["created_at"] = real_now_iso()
        if mutable:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row["_seq"] = self.next_seq()
        getattr(self, collection)[row["id"]] = row
        return row

    def rows(self, collection):
        return sort_rows(list(getattr(self, collection).values()))


store = Store()
