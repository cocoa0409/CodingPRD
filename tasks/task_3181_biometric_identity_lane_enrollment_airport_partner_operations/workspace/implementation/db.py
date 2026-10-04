"""In-memory data store + logical clock.

The store starts completely empty on every boot. No seeding of any kind.
The logical clock defaults to 2026-09-01T00:00:00Z and only moves via
POST /_clock/set_current_utc.
"""
import threading
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.members = {}
        self.enrollments = {}
        self.kiosks = {}
        self.enrollment_centers = {}
        self.ambassadors = {}
        self.airports = {}
        self.partner_agreements = {}
        self.lanes = {}
        self.venues = {}
        self.venue_events = {}
        self.subscriptions = {}
        self.family_groups = {}
        self.partner_discounts = {}
        self.lane_verifications = {}
        self.venue_access_events = {}
        self.identity_disputes = {}
        self.biometric_retention_logs = {}
        self.agreement_settlements = {}
        self.subscription_invoices = {}
        # fraud watchlist: set of (document_number, date_of_birth)
        self.watchlist = set()
        # members whose biometric data has been purged (set of member_id)
        self.purged_members = set()
        # logical clock (datetime, tz-aware UTC)
        self.clock = _parse_dt(DEFAULT_CLOCK_ISO)
        # flag: has the clock been advanced past default (date boundary sweep)
        self._last_sweep_date = self.clock.date()

    def now(self):
        return self.clock


def _parse_dt(value):
    """Parse an ISO 8601 string into a tz-aware datetime (UTC assumed if naive)."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD) or datetime into a date."""
    from datetime import date
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()
    if "T" in s:
        return _parse_dt(s).date()
    parts = s.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def fmt_dt(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits and Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


# single global store instance (per process)
store = Store()
