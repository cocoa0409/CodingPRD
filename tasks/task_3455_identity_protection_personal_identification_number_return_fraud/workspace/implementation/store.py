"""In-memory data store and logical clock.

State lives only in process memory; every fresh `start.sh` boot yields a
totally empty store. The logical clock starts at exactly 2026-09-01T00:00:00Z
and never falls back to wall-clock time.
"""
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(s):
    """Parse an ISO 8601 timestamp (with 'Z' or numeric offset) to aware UTC.

    Returns None when the value is not a parseable datetime string.
    """
    if not isinstance(s, str):
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.taxpayers = {}
        self.reports = {}
        self.pins = {}
        self.preparers = {}
        self.returns = {}
        self.holds = {}
        self.cases = {}
        self.documents = {}
        self.offices = {}
        self.appointments = {}
        self.claims = {}
        self.conflicts = {}
        self.alerts = {}
        self.disbursements = {}
        self.advocate_cases = {}
        self.configs = {}
        self.seq = 0
        self.clock = CLOCK_START

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_ts(self.clock)

    def set_clock(self, dt):
        self.clock = dt.astimezone(timezone.utc)


DB = Store()
