"""In-memory data store and logical clock.

The store starts empty on every boot — the implementation MUST NOT seed any
entities at startup. Every entity any test needs is constructed through the
declared API surface.
"""
import datetime

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.10): defaults to 2026-09-01T00:00:00Z and NEVER falls
# back to wall-clock time.
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.clock_iso = _DEFAULT_CLOCK
        # Primary resource tables, keyed by id.
        self.fund_companies = {}
        self.funds = {}
        self.holdings = {}          # ledger rows
        self.categories = {}
        self.methodologies = {}
        self.methodology_changes = {}
        self.ratings = {}
        self.proposals = {}
        self.votes = {}             # ledger rows
        self.licensees = {}
        self.agreements = {}
        self.seats = {}
        self.audits = {}
        self.disputes = {}
        self.indices = {}
        self.constituents = {}      # ledger rows
        self.conflict_flags = {}
        self.client_notices = {}    # ledger rows

    # ---- logical clock helpers ----
    def clock_datetime(self):
        return _parse_iso(self.clock_iso)

    def clock_date_str(self):
        return self.clock_datetime().date().isoformat()

    def set_clock(self, iso):
        self.clock_iso = _normalize_to_z(iso)


def _parse_iso(iso):
    """Parse an ISO-8601 string (with Z or offset) into an aware UTC datetime."""
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _normalize_to_z(iso):
    """Normalize an ISO-8601 string to UTC 'Z' form with 3 fractional digits."""
    dt = _parse_iso(iso)
    return _fmt_dt(dt)


def _fmt_dt(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def now_iso():
    """Wall-clock timestamp used for created_at/updated_at/request timestamps.
    ISO 8601 UTC with three fractional digits."""
    return _fmt_dt(datetime.datetime.now(datetime.timezone.utc))


store = Store()
