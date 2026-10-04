"""In-memory data store and logical clock. Store starts empty every boot."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: deterministic, default 2026-09-01T00:00:00Z.
        self.now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.users = {}              # id -> User
        self.pages = {}              # id -> BusinessPage
        self.reviews = {}            # id -> Review
        self.claims = {}             # id -> PageClaim
        self.ad_accounts = {}        # id -> AdAccount
        self.campaigns = {}          # id -> AdCampaign
        self.impressions = {}        # id -> AdImpressionEvent
        self.call_events = {}        # id -> CallTrackEvent
        self.reports = {}            # id -> AttributionReport
        self.complaints = {}         # id -> Complaint
        self.cases = {}              # id -> SolicitationCase
        self.alerts = {}             # id -> ConsumerAlert
        self.identity_requests = {}  # id -> IdentityRequest
        self.merge_requests = {}     # id -> MergeRequest

    def now_iso(self):
        return fmt_ts(self.now)


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def parse_ts(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z). Returns aware datetime."""
    if isinstance(s, str):
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    raise ValueError("not a timestamp string")


def parse_date(s):
    """Parse YYYY-MM-DD into a date."""
    return datetime.strptime(s, "%Y-%m-%d").date()


store = Store()
