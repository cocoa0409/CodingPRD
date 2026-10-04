import threading
import uuid
from datetime import datetime, timezone


class Store:
    """In-memory only. Fresh on every process boot; never seeded."""

    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: starts at exactly 2026-09-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic insertion counter; created_at tiebreak for sweeps
        self.installations = {}
        self.members = {}
        self.applications = {}
        self.employers = {}
        self.openings = {}
        self.matches = {}
        self.supervision_reports = {}
        self.wage_records = {}
        self.audits = {}
        self.conversions = {}


store = Store()


def now():
    return store.clock


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def base_entity():
    """Common fields for the seven principal resources (id/created_at/updated_at/version)."""
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def ledger_entity():
    """Ledger resources (SupervisionReport/WageRecord/ConversionRecord): id + created_at only."""
    return {"id": new_id(), "created_at": now(), "_seq": next_seq()}
