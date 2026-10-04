"""In-memory data store.

Storage is deliberately ephemeral: plain dicts keyed by id, rebuilt empty on every
process boot. Nothing is seeded, preloaded or persisted -- every entity a test needs
is constructed through the declared API surface. The per-test-server harness wipes
all state by re-invoking start.sh.
"""

import uuid
from datetime import datetime, timezone

import clock


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:20].upper()


def utc_now_stamp():
    """Envelope timestamp: real UTC with three fractional digits (PRD 2.2)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    """Holds every collection plus the single SystemConfig row."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.accounts = {}
        self.subscriber_lines = {}
        self.port_requests = {}
        self.promo_credit_schedules = {}
        self.device_installment_plans = {}
        self.trade_in_assessments = {}
        self.number_reservations = {}
        self.migration_requests = {}
        self.line_addition_requests = {}
        self.port_protection_cases = {}
        self.rejection_code_catalog = {}

        # SystemConfig is a singleton row materialized on first read. Its clock
        # default (2026-09-01T00:00:00Z) is a system constant, not entity data.
        self.system_config = None

    # -- generic helpers ----------------------------------------------------
    def collection(self, name):
        return getattr(self, name)

    def add(self, name, record):
        self.collection(name)[record["id"]] = record
        return record

    def get(self, name, entity_id):
        return self.collection(name).get(entity_id)

    def all(self, name):
        return list(self.collection(name).values())


db = Store()


def init_system_config():
    """Create the singleton SystemConfig row (system constants only)."""
    if db.system_config is None:
        db.system_config = {
            "id": new_id(),
            "ops_run_epoch": 1,
            "last_ops_run_at": clock.CLOCK_DEFAULT,
            "last_line_cancellation_deadline": clock.CLOCK_DEFAULT,
            "line_cancellation_grace_hours": 24,
            "promo_window_buffer_days": 30,
            "created_at": clock.fmt_now(),
            "updated_at": clock.fmt_now(),
            "version": 1,
        }
    return db.system_config