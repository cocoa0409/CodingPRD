"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
The logical clock starts at 2026-09-01T00:00:00Z and can be advanced by a
PlatformAdmin via POST /_clock/set_current_utc.
"""
import threading
from datetime import datetime, timezone


DEFAULT_START = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware datetime (UTC)."""
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc) if s.tzinfo else s.replace(tzinfo=timezone.utc)
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits and Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _parse_iso(DEFAULT_START)
        self.editors = {}               # id -> VolunteerEditor
        self.pages = {}                 # id -> WikiPage
        self.revisions = {}             # id -> Revision
        self.disputes = {}              # id -> DisputeCase
        self.protection_requests = {}   # id -> ProtectionRequest
        self.vandalism_reports = {}     # id -> VandalismReport
        self.campaigns = {}             # id -> DonationCampaign
        self.banners = {}               # id -> CampaignBanner
        self.donations = {}             # id -> Donation
        self.grant_programs = {}        # id -> GrantProgram
        self.grant_applications = {}    # id -> GrantApplication
        self.legal_requests = {}        # id -> LegalRequest
        self.transparency_reports = {}  # id -> TransparencyReport
        self.impressions = {}           # id -> ImpressionEvent

    def now(self):
        return self.clock

    def now_iso(self):
        return _format_iso(self.clock)

    def set_clock(self, iso):
        self.clock = _parse_iso(iso)


db = Store()
