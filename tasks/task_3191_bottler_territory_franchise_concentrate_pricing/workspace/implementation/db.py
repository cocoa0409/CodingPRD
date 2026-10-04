import secrets
import string
import threading
from datetime import datetime, timezone

_lock = threading.Lock()

# Logical clock: starts at 2026-09-01T00:00:00Z, never falls back to wall clock.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
_current_clock = DEFAULT_CLOCK


def get_clock():
    return _current_clock


def set_clock(value):
    global _current_clock
    with _lock:
        _current_clock = value


def parse_iso(ts):
    """Parse ISO 8601 timestamp (date or datetime). Returns aware datetime."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (wall clock for meta)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(22))


class Store:
    """In-memory store; fresh on every process boot. No seeding."""

    def __init__(self):
        self.brand_owners = {}
        self.territories = {}
        self.agreements = {}
        self.product_lines = {}
        self.price_indices = {}
        self.cpos = {}
        self.ncas = {}
        self.customers = {}
        self.dsd_orders = {}
        self.equipment = {}
        self.service_windows = {}
        self.fountain_accounts = {}
        self.syrup_deliveries = {}
        self.transfers = {}
        self.launches = {}
        self.fund_entries = {}


db = Store()
