"""In-memory data store. Fresh, empty on every process boot. No persistence."""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock timestamp for created_at/updated_at (3 fractional digits, Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string to an aware datetime (UTC assumed for 'Z')."""
    if isinstance(s, str):
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError("not a datetime string")


class Store:
    """Whole application state lives here; module-level singleton, empty at boot."""

    def __init__(self):
        self.rollouts = {}            # id -> dict
        self.trade_areas = {}         # id -> dict
        self.stores = {}              # id -> dict
        self.developers = {}          # id -> dict
        self.agreements = {}          # id -> dict
        self.dcs = {}                 # id -> dict
        self.dc_assignments = {}      # id -> dict
        self.route_plans = {}         # id -> dict
        self.opening_plans = {}       # id -> dict
        self.studies = {}             # id -> dict
        self.events = {}              # id -> dict
        self.capital_projects = {}    # id -> dict
        self.clocks = {}              # rollout_id -> aware datetime

    def get_clock(self, rollout_id):
        dt = self.clocks.get(rollout_id)
        if dt is None:
            dt = parse_iso(DEFAULT_CLOCK_ISO)
            self.clocks[rollout_id] = dt
        return dt

    def set_clock(self, rollout_id, iso_str):
        self.clocks[rollout_id] = parse_iso(iso_str)
        return self.clocks[rollout_id]


DB = Store()
