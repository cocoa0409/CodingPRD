"""In-memory data store for the Bank Data Connectivity Consent API.

All storage is in Python dicts keyed by id. No files, no SQLite, no seed data.
The store starts empty on every boot.
"""

import uuid
from datetime import datetime, timezone

# --- entity stores (dicts keyed by id) ---
institutions = {}
agreements = {}
recipients = {}
consents = {}
connections = {}
data_scope_grants = {}
tiers = {}
refresh_jobs = {}
webhook_events = {}
breakage_events = {}
deletion_requests = {}
tier_assignments = {}
audit_logs = {}

# Logical clock — default 2026-09-01T00:00:00Z
_CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_clock = _CLOCK_DEFAULT


def new_id():
    return str(uuid.uuid4())


def get_clock():
    return _current_clock


def set_clock(dt):
    global _current_clock
    _current_clock = dt


def now_iso():
    """Return current clock time as ISO8601 with 3 fractional digits, Z suffix."""
    dt = _current_clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ts_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
