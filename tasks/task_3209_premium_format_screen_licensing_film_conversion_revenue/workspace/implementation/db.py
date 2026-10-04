"""In-memory data store and logical clock.

Store starts empty on every boot — no seeding.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.markets = {}
        self.agreements = {}
        self.auditoriums = {}
        self.studios = {}
        self.films = {}
        self.conversion_orders = {}
        self.release_windows = {}
        self.screen_slots = {}
        self.box_office_reports = {}
        self.revenue_share_statements = {}
        self.qa_alerts = {}
        self.tech_dispatches = {}
        # Logical clock: default before any set call.
        self.logical_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()
