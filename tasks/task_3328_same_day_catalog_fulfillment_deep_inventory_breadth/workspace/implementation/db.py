"""In-memory data store.

Everything lives in plain dicts keyed by id. Nothing is written to disk, no
state survives a process exit, and nothing is seeded at import or startup:
the store is empty until the API surface creates records. Each per-test
server reboot therefore starts from a completely blank world.

The logical clock starts at exactly 2026-09-01T00:00:00Z (SCAFFOLD section
1.1 ClockTick, PRD section 2.5) and is only ever moved by
POST /_clock/set_current_utc -- never by wall-clock time.
"""

import uuid
from datetime import datetime, timedelta

DEFAULT_CLOCK_UTC = datetime(2026, 9, 1, 0, 0, 0)


def parse_iso(value):
    """Parse an ISO 8601 instant, tolerating a trailing Z and missing fraction."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def iso_millis(dt):
    """ISO 8601 UTC string with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self):
        self.reset()

    # ------------------------------------------------------------------
    def reset(self):
        self.current_utc = DEFAULT_CLOCK_UTC
        self.dc_local_times = {}

        self.distribution_centers = {}
        self.dc_holds = {}          # dc_id -> list of open hold dicts
        self.suppliers = {}
        self.supplier_availability_reports = {}
        self.curation_reviews = {}
        self.curation_review_items = {}
        self.catalog_items = {}
        self.item_attributes = {}
        self.item_cross_references = {}
        self.stock_rows = {}
        self.accounts = {}
        self.orders = {}
        self.order_lines = {}
        self.pick_tasks = {}
        self.shipments = {}
        self.return_authorizations = {}
        self.return_lines = {}
        self.damage_claims = {}
        self.square_footage_requests = {}
        self.square_footage_lines = {}

        self._seq = 0

    # ------------------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        """Logical 'now' -- the clock instant, never the machine clock."""
        return iso_millis(self.current_utc)

    # ------------------------------------------------------------------
    def stamp(self, record, common=True):
        """Apply identity / timestamp / version common fields to a new row."""
        record.setdefault("id", self.new_id())
        ts = self.now_iso()
        record["created_at"] = ts
        if common:
            record["updated_at"] = ts
            record["version"] = 1
        record["_seq"] = self.next_seq()
        return record

    def touch(self, record):
        """Refresh updated_at and bump version for a mutating write."""
        record["updated_at"] = self.now_iso()
        record["version"] = record.get("version", 1) + 1
        return record


# Module-level singleton used by the application. It is empty on import.
db = Store()


def created_key(record):
    """Deterministic 'insertion order' key standing in for created_at ASC."""
    return (record.get("created_at", ""), record.get("_seq", 0))


def local_datetime(current_utc, utc_offset_minutes):
    """A DC's local wall-clock datetime = current_utc + utc_offset_minutes."""
    return current_utc + timedelta(minutes=utc_offset_minutes)


def local_time_string(current_utc, utc_offset_minutes):
    """A DC's local wall-clock time as the HH:MM:SS string the spec stores."""
    return local_datetime(current_utc, utc_offset_minutes).strftime("%H:%M:%S")