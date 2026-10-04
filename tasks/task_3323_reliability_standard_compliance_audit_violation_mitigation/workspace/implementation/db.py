"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity tables keyed by id
        self.registered_entities = {}
        self.engagements = {}
        self.evidence = {}
        self.self_reports = {}
        self.violations = {}
        self.mitigation_plans = {}
        self.milestones = {}
        self.self_log_entries = {}
        self.review_periods = {}
        self.cip_assets = {}
        self.access_grants = {}
        self.penalties = {}
        self.appeals = {}
        # logical clock: default before any operator call
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()
