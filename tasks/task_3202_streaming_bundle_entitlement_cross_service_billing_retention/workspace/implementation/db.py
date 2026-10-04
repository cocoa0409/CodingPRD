"""In-memory data store for the streaming bundle entitlement API."""
import threading
from datetime import datetime, timezone

# The logical clock startup default per PRD 2.5.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = str(s)
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    """Format as ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return "%s.%03dZ" % (base, ms)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _parse_iso(DEFAULT_CLOCK_ISO)
        self.plans = {}                 # plan_code -> dict
        self.accounts = {}              # id -> dict
        self.profiles = {}              # id -> dict
        self.watchlist_items = {}       # id -> dict
        self.billing_accounts = {}      # id -> dict
        self.subscriptions = {}         # id -> dict
        self.entitlements = {}          # id -> dict
        self.migrations = {}            # id -> dict
        self.offers = {}                # offer_code -> dict
        self.redemptions = {}           # id -> dict
        self.invoices = {}              # id -> dict
        self.revenue_allocations = {}   # id -> dict

    def now(self):
        return self.clock

    def now_iso(self):
        return _fmt_iso(self.clock)


store = Store()
