"""In-memory data store. Fresh, empty store per process boot."""
import os
import uuid
import threading
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def _parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(s):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    return _parse_iso(s)


def fmt_dt(dt):
    """Format aware UTC datetime as ISO8601 with three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.employers = {}
        self.rating_tables = {}
        self.policies = {}
        self.class_codes = {}          # PolicyClassCode
        self.integrations = {}
        self.reports = {}              # PayrollReport
        self.lines = {}                # PayrollLine
        self.invoices = {}             # PremiumInvoice
        self.disputes = {}             # ClassCodeDispute
        self.audits = {}               # AuditReconciliation
        self.tax_filings = {}          # TaxFilingRecord
        self.clock = _parse_iso(DEFAULT_CLOCK)
        self._insert_counter = 0

    def next_seq(self):
        self._insert_counter += 1
        return self._insert_counter

    def register(self, coll_name, rec):
        rec["_seq"] = self.next_seq()
        getattr(self, coll_name)[rec["id"]] = rec
        return rec

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


STORE = Store()
LOCK = _lock
