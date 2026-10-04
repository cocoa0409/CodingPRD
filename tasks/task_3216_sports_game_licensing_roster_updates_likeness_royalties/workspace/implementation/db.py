"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding of any entity.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.agreements: dict = {}
        self.athletes: dict = {}
        self.likeness_grants: dict = {}
        self.seasons: dict = {}
        self.roster_batches: dict = {}
        self.roster_entries: dict = {}
        self.content_drops: dict = {}
        self.wallets: dict = {}
        self.ledger_entries: dict = {}
        self.tournaments: dict = {}
        self.tournament_entries: dict = {}
        self.tournament_prizes: dict = {}
        self.audio_assets: dict = {}
        self.audio_licenses: dict = {}
        self.editions: dict = {}
        self.royalty_statements: dict = {}
        self.audit_cases: dict = {}
        # logical clock; startup default exactly 2026-09-01T00:00:00Z
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    # -- clock helpers -----------------------------------------------------
    def now(self) -> datetime:
        return self.clock

    def now_date(self):
        return self.clock.date()

    def set_clock(self, dt: datetime) -> None:
        self.clock = dt


db = Store()
