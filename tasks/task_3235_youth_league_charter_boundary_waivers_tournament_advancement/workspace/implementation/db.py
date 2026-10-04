"""In-memory data store. Empty at every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits (wall clock for metadata)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    """Single logical clock. Startup default exactly 2026-09-01T00:00:00Z;
    never falls back to wall-clock time."""

    def __init__(self):
        self._iso = "2026-09-01T00:00:00Z"

    def set(self, iso):
        self._iso = iso

    def iso(self):
        return self._iso

    def date(self):
        # YYYY-MM-DD of the current logical clock
        return self._iso[:10]


class DB:
    def __init__(self):
        self.leagues = {}
        self.renewals = {}
        self.divisions = {}
        self.players = {}
        self.documents = {}
        self.waivers = {}
        self.volunteers = {}
        self.screenings = {}
        self.certificates = {}
        self.rosters = {}
        self.entries = {}
        self.games = {}
        self.appearances = {}
        self.protests = {}
        self.clock = LogicalClock()
        # monotonically increasing creation sequence for created_at tie-breaks
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()
