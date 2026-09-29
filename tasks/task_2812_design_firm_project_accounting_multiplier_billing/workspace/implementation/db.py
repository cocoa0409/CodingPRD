"""In-memory data store and the logical clock (PRD 2.6).

Storage is process-local and in-memory only. Every boot starts completely
empty -- no entity is ever seeded, preloaded or hardcoded here.
"""
import uuid
from datetime import datetime, timezone

# PRD 2.6: "Before the clock is ever set explicitly, it reads exactly
# 2026-08-01T00:00:00Z. The server must never fall back to real wall-clock time."
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.clients = {}
        self.projects = {}
        self.phases = {}
        self.labor_rates = {}
        self.billing_multipliers = {}
        self.time_entries = {}
        self.expenses = {}
        self.subcontracts = {}
        self.consultant_invoices = {}
        self.invoices = {}
        self.write_offs = {}
        self.certifications = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """PRD 2.4: a server-minted UUID string carrying no type prefix."""
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(db.clock)


def today():
    """Calendar date of the logical clock."""
    return db.clock.astimezone(timezone.utc).date()


def current_year():
    return today().year
