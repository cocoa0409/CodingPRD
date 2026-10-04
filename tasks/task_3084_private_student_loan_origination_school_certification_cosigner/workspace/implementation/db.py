"""In-memory data store.

The store is a set of plain dicts keyed by id. It is created empty at process
start and MUST NOT be seeded with any entity data: every entity a test needs is
constructed through the declared API surface. Because the whole store lives in
process memory, re-invoking start.sh (per-test-server isolation) wipes every
byte of state.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock never falls back to wall-clock time. PRD 2.5 / SCAFFOLD
# _clock/set_current_utc: the fixed server default is 2026-09-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def utcnow_iso():
    """Real wall-clock stamp for the envelope meta only (api_request_timestamp).

    Resource created_at/updated_at are stamped from the LOGICAL clock so that
    derived/timestamp comparisons stay deterministic.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Advance a datetime by whole calendar months, clamping the day."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = dt.day
    while day > 28:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
    return dt.replace(year=year, month=month, day=day)


class Store:
    """One dict per entity type, plus the logical clock and an id counter."""

    def __init__(self):
        self.borrowers = {}
        self.cosigners = {}
        self.schools = {}
        self.policies = {}
        self.applications = {}
        self.certifications = {}
        self.loans = {}
        self.disbursements = {}
        self.accrual_entries = {}
        self.repayment_plans = {}
        self.payments = {}
        self.forbearances = {}
        self.release_applications = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.lock = threading.RLock()

    # -- identity ----------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        """A strictly monotonic creation counter, used as the created_at tie
        breaker in the certification waterfall ordering."""
        self._seq += 1
        return self._seq

    # -- logical clock -----------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


db = Store()