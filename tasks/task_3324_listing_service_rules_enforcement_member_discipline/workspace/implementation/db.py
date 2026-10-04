"""In-memory data store + logical clock. The store starts empty on every boot;
no entity is ever seeded at startup (skill contract)."""

import threading
from datetime import datetime, timezone, timedelta

_lock = threading.RLock()

# Logical clock: server startup default is exactly 2026-09-01T00:00:00.000Z.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00.000Z"


def _parse_iso(s):
    """Parse an ISO 8601 timestamp (with Z or offset) into an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with exactly 3 fractional digits + Z."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


class Store:
    def __init__(self):
        self.associations = {}          # id -> dict
        self.policy_revisions = {}      # id -> dict
        self.members = {}               # id -> dict
        self.offices = {}               # id -> dict
        self.dues_periods = {}          # id -> dict
        self.dues_invoices = {}         # id -> dict
        self.listings = {}              # id -> dict
        self.status_changes = {}        # id -> dict
        self.citations = {}             # id -> dict
        self.fine_schedules = {}        # id -> dict
        self.ethics_cases = {}          # id -> dict
        self.arbitration_cases = {}     # id -> dict
        self.hearing_panels = {}        # id -> dict
        self.data_licenses = {}         # id -> dict
        self.consolidation_events = {}  # id -> dict
        # Logical clock
        self.clock = _parse_iso(DEFAULT_CLOCK_ISO)
        # Per-member reinstatement instants (SUSPENDED -> ACTIVE), for strikes_12m
        self.reinstatements = {}        # member_id -> [datetime, ...]
        # Per-member suspension tracking: member_id -> {"suspended_at": dt,
        #   "trigger_grace_end_date": dt}
        self.suspensions = {}


store = Store()


def now():
    """Current logical instant (aware UTC datetime)."""
    return store.clock


def now_iso():
    return _fmt_iso(store.clock)


def set_clock(dt):
    store.clock = dt


def advance_days(days):
    store.clock = store.clock + timedelta(days=days)


def lock():
    return _lock
