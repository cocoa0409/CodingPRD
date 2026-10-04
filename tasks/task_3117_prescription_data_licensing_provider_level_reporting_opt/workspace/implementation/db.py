"""In-memory data store. Empty at every boot; no seeding whatsoever."""

from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class DB:
    def __init__(self):
        self.clients = {}
        self.suppliers = {}
        self.agreements = {}
        self.deid_profiles = {}
        self.batches = {}
        self.prescribers = {}
        self.opt_outs = {}
        self.jurisdiction_rules = {}
        self.methodologies = {}
        self.projection_cells = {}
        self.products = {}
        self.periods = {}
        self.deliveries = {}
        self.audit_events = {}
        # Logical clock; never falls back to wall-clock time.
        self.logical_clock = datetime(2026, 9, 1, tzinfo=timezone.utc)


db = DB()
