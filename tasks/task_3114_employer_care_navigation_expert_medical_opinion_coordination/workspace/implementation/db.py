"""In-memory data store and logical clock."""
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.employers = {}
        self.members = {}
        self.coverage_windows = {}
        self.providers = {}
        self.quality_snapshots = {}
        self.consents = {}
        self.navigation_cases = {}
        self.appointments = {}
        self.record_requests = {}
        self.expert_opinions = {}
        self.opinion_items = {}
        self.claims = {}
        self.billing_cases = {}
        self.authorizations = {}
        self.clock = _parse_dt(DEFAULT_CLOCK)


def _parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


db = Store()
