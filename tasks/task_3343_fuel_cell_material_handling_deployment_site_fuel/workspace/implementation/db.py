"""In-memory data store and the platform logical clock (PRD section 2.5).

The store starts empty on every boot; all entities are created through the
declared API surface. The logical clock defaults to 2026-09-01T00:00:00Z and
never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Entity stores: id -> record dict
sites = {}
assessments = {}
contracts = {}
stations = {}
permits = {}
plans = {}
events = {}
technicians = {}
agreements = {}
downtime_reports = {}
fueling_events = {}
invoices = {}
line_items = {}
claims = {}
training_records = {}

_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_last_stamp = None


def new_id():
    return str(uuid.uuid4())


def logical_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def current_date():
    return _clock.date()


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def stamp():
    """Logical-clock based timestamp, strictly increasing across the process.

    Used for created_at / updated_at / meta timestamps so that ordering by
    created_at is deterministic even when several records are created at the
    same logical instant.
    """
    global _last_stamp
    candidate = _clock
    if _last_stamp is not None and candidate <= _last_stamp:
        candidate = _last_stamp + timedelta(milliseconds=1)
    _last_stamp = candidate
    return _fmt(candidate)


def clock_stamp():
    """Exact logical clock timestamp (no monotonic bump).

    Used for commissioned_at / terminated_at / completed_at, which are
    compared against client-supplied datetimes.
    """
    return _fmt(_clock)
