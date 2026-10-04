"""In-memory data store and logical clock.

The store starts completely empty on every boot. Nothing is seeded.
"""
import threading
from datetime import datetime, timezone

_lock = threading.RLock()

INITIAL_CLOCK = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.clock = _parse(INITIAL_CLOCK)
        # collections keyed by id
        self.plants = {}
        self.suppliers = {}
        self.collection_programs = {}
        self.feedstock_lots = {}
        self.formulations = {}
        self.product_lines = {}
        self.dealers = {}
        self.shipment_orders = {}
        self.stocking_commitments = {}
        self.allocation_commitments = {}
        self.production_runs = {}
        self.board_lots = {}
        self.contractors = {}
        self.training_modules = {}
        self.training_records = {}
        self.lead_referrals = {}
        self.install_registrations = {}
        self.warranty_claims = {}
        self.claim_samples = {}
        self.sample_kits = {}
        self.color_chip_requests = {}
        self.price_books = {}
        # per-plant internal bookkeeping (not exposed): last review date (ISO date str)
        self.plant_review_state = {}
        # formulation revision history: formulation_id -> {revision_no: {"lines": [...], "hash": str}}
        self.formulation_revisions = {}
        # per-plant PCR support-stock tracking: plant_id -> {"production_lbs": int, "support_lbs": int}
        # tracks provenance of PCR_FILM mass in resin_store for the support-stock bar
        self.pcr_origin = {}
        # per-plant PCR decay baseline: plant_id -> {"anchor_date": iso date, "balance_at_anchor": int}
        self.pcr_decay_anchor = {}
        # request counter for ids
        self.req_counter = 0


def _parse(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db = Store()


def lock():
    return _lock


def clock_now():
    return db.clock


def clock_date():
    return db.clock.date()


def set_clock(iso_str):
    db.clock = _parse(iso_str)
