"""In-memory data store and logical clock. Everything lives in module-level dicts;
a fresh process starts completely empty (no seeding)."""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    t = str(s).replace("Z", "+00:00")
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{s}.{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    """created_at/updated_at timestamps: ISO 8601 UTC, three fractional digits."""
    return fmt_iso(datetime.now(timezone.utc))


class Store:
    def __init__(self):
        self.sellers = {}
        self.buyers = {}
        self.programs = {}
        self.listings = {}
        self.reports = {}
        self.leases = {}
        self.payments = {}
        self.uw_reports = {}
        self.offers = {}
        self.escrows = {}
        self.pms = {}
        self.referrals = {}
        self.guarantees = {}
        self.disputes = {}
        # Logical clock (never wall-clock) for all temporal business logic
        self.clock = _parse_iso(DEFAULT_CLOCK)

    def clock_iso(self):
        return fmt_iso(self.clock)


store = Store()
