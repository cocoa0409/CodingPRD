"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

# Logical clock: default 2026-09-01T00:00:00Z, advanced only via admin endpoint.
class _Clock:
    def __init__(self):
        self._current = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt

clock = _Clock()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def now_iso():
    return iso_format(clock.now())


def iso_format(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return s


# entity stores: id -> dict
advisors = {}
territories = {}
contacts = {}
branches = {}
administrators = {}
training_programs = {}
milestone_evaluations = {}
leases = {}
financial_periods = {}
charges = {}
production_records = {}
goodwill_transfers = {}
product_shelf = {}
solicitation_requests = {}
