"""In-memory data store. Fresh on every process boot — no disk persistence,
no seeding. The store starts empty; every entity is created via the API."""
import itertools
import uuid
from datetime import datetime, timezone

CLOCK_START_ISO = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        # Logical program clock (PRD section 2.6); starts at 2026-09-01T00:00:00Z.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = itertools.count(1)  # insertion order tie-breaker
        self.agents = {}
        self.vendors = {}
        self.capacity_windows = {}
        self.cases = {}
        self.projects = {}
        self.engagements = {}
        self.disbursements = {}
        self.change_orders = {}
        self.disputes = {}
        self.closing_statements = {}
        self.listing_events = {}


store = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


def now():
    return store.clock


def next_seq():
    return next(store.seq)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
