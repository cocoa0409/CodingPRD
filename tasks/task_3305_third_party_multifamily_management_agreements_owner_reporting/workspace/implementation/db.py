"""In-memory data store and logical clock."""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Logical clock state: a dict so modules can mutate via helper
_clock = {"current": None}


def _parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def get_clock():
    if _clock["current"] is None:
        return _parse_iso(DEFAULT_CLOCK_ISO)
    return _clock["current"]


def set_clock(iso_str):
    _clock["current"] = _parse_iso(iso_str)
    return _clock["current"]


def now_iso():
    """Current logical-clock time rendered as ISO 8601 with Z."""
    dt = get_clock()
    return _format_iso(dt)


def real_now_iso():
    """Real wall-clock time for meta timestamps (3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return _format_iso(dt)


def _format_iso(dt):
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.astimezone(timezone.utc).microsecond // 1000
    return f"{s}.{ms:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    """In-memory store; recreated per process start (no seeding)."""

    def __init__(self):
        self.owners = {}                 # id -> dict
        self.properties = {}             # id -> dict
        self.agreements = {}             # id -> dict
        self.onboardings = {}            # id -> dict
        self.residents = {}              # id -> dict
        self.vendor_contracts = {}       # id -> dict
        self.budgets = {}                # id -> dict
        self.pricing = {}                # id -> dict
        self.staff = {}                  # id -> dict
        self.statements = {}             # id -> dict
        self.ledger = {}                 # id -> dict
        self.reports = {}                # id -> dict
        self.claims = {}                 # id -> dict
        self.claim_settlements = {}      # id -> dict


db = Store()
