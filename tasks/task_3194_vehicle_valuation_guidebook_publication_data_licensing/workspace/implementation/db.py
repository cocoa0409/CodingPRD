"""In-memory data store plus the logical clock.

State is held in module-level dicts that start empty on every boot — the
harness restarts the server per test, so there is no carry-over between runs.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone


# Logical clock; default per PRD §2.4
_DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


class _Clock:
    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value


CLOCK = _Clock()


class _DB:
    """Container for all entity dicts. Each maps id -> entity dict."""

    def __init__(self):
        self.regions = {}
        self.sources = {}
        self.configurations = {}
        self.option_packages = {}
        self.batches = {}
        self.corrections = {}
        self.series = {}
        self.editions = {}
        self.market_shifts = {}
        self.consumer_profiles = {}
        self.cash_offers = {}
        self.license_agreements = {}
        self.license_events = {}
        self.methodologies = {}
        self.condition_standards = {}
        self.disputes = {}
        self.snapshots = {}
        # Idempotency indices
        self._source_external_keys = {}        # external_key -> source_id
        self._config_external_keys = {}        # external_key -> configuration_id
        self._series_external_keys = {}        # external_key -> series_id
        self._batch_submission_refs = {}       # submission_ref -> batch_id
        # Email uniqueness
        self._consumer_emails = {}             # email -> profile_id
        # Condition tier uniqueness
        self._condition_tiers = {}             # tier -> standard_id
        # Methodology version_label uniqueness
        self._methodology_labels = {}          # version_label -> methodology_id
        # Region code uniqueness
        self._region_codes = {}                # region_code -> region_id


DB = _DB()


def reset_db() -> None:
    """Reset all in-memory state (used only for safety between imports)."""
    global DB
    DB = _DB()
