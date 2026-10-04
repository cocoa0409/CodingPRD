"""In-memory store, logical clock, and low-level helpers.

The store starts empty on every boot (per-test-server isolation re-launches
the process). The platform never reads wall-clock time: the logical clock
starts fixed at 2026-09-01T00:00:00Z and only moves via the clock endpoint.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_CLOCK = CLOCK_START

STORES = {
    "organizations": {},
    "dealers": {},
    "machines": {},
    "data_plans": {},
    "field_boundaries": {},
    "prescriptions": {},
    "data_share_grants": {},
    "consent_tickets": {},
    "diagnostic_sessions": {},
    "software_packages": {},
    "update_deliveries": {},
    "feature_licenses": {},
    "warranty_claims": {},
    "integration_partners": {},
}

# machine_id -> {batch_id: {"start": datetime, "hour_count": int, "payload_mb": Decimal}}
TELEMETRY = {}

_SEQ = [0]


def now():
    return _CLOCK


def set_clock(t):
    global _CLOCK
    _CLOCK = t


def new_id():
    return uuid.uuid4().hex


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def iso(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    """Parse an ISO 8601 timestamp (Z or numeric offset) to an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Parse a strict ISO calendar date (YYYY-MM-DD)."""
    if not isinstance(s, str) or not _DATE_RE.match(s.strip()):
        raise ValueError("not an ISO date")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()
