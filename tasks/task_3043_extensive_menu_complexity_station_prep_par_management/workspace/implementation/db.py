import uuid
from datetime import datetime, timezone


class Store:
    """In-memory data store. Starts empty on every boot — never seeded."""

    def __init__(self):
        self.restaurants = {}
        self.menu_revisions = {}
        self.recipes = {}
        self.prep_items = {}
        self.stations = {}
        self.station_pars = {}
        self.cooks = {}
        self.demand_forecasts = {}
        self.prep_lists = {}
        self.prep_batches = {}
        self.shift_assignments = {}
        self.bakery_orders = {}
        self.waste_entries = {}
        self.service_tickets = {}
        # Insertion order tracking per collection for created_at ordering ties
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
_clock_now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Timestamp for created_at/updated_at: logical clock, 3 fractional digits, Z."""
    return format_iso(clock_now())


def format_iso(dt):
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.astimezone(timezone.utc).microsecond // 1000
    return f"{s}.{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
