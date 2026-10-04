"""In-memory data store and the logical clock.

Storage is process-local only: plain dicts keyed by id. Every byte of state
vanishes when the process exits; nothing is seeded at startup.
"""
import threading
import uuid
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def parse_clock_iso(s):
    """Parse an ISO 8601 instant (accepts trailing Z and offsets)."""
    if not isinstance(s, str):
        raise ValueError("clock value must be a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.applicants = {}
        self.applications = {}
        self.centers = {}
        self.trade_programs = {}
        self.enrollments = {}
        self.dormitory_assignments = {}
        self.conduct_incidents = {}
        self.credentials = {}
        self.employer_agreements = {}
        self.wbl_placements = {}
        self.transition_plans = {}
        self.operator_contracts = {}
        self.performance_snapshots = {}
        # Logical clock: before any set call it reads exactly the default and
        # never falls back to wall-clock time.
        self.clock = parse_clock_iso(DEFAULT_CLOCK_ISO)
        self.clock_echo = DEFAULT_CLOCK_ISO
        # Monotonic source for created_at/updated_at/meta timestamps so that
        # created_at ASC ordering is always deterministic.
        self._ts_epoch = datetime.now(timezone.utc)
        self._ts_seq = 0
        self._rec_seq = 0

    def new_id(self):
        # Canonical 8-4-4-4-12 dashed UUID string form (PRD 2.5: "server-minted
        # UUID with no type prefix").
        return str(uuid.uuid4())

    def tick(self):
        """Strictly increasing ISO 8601 UTC timestamp (3 fractional digits)."""
        self._ts_seq += 1
        return fmt_ts(self._ts_epoch + timedelta(milliseconds=self._ts_seq))

    def clock_date(self):
        return self.clock.date()

    def clock_date_str(self):
        return self.clock.date().isoformat()

    def clock_ts(self):
        return fmt_ts(self.clock)

    def set_clock(self, iso_text):
        self.clock = parse_clock_iso(iso_text)
        self.clock_echo = iso_text


STORE = Store()


def new_record():
    """Common fields for every entity except PerformanceSnapshot."""
    ts = STORE.tick()
    STORE._rec_seq += 1
    return {
        "id": STORE.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": STORE._rec_seq,
    }


def bump(rec):
    """Every mutation of a resource advances its own version by exactly 1."""
    rec["updated_at"] = STORE.tick()
    rec["version"] += 1
