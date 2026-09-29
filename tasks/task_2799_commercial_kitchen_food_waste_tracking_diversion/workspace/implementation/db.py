"""In-memory data store and the logical clock.

The store starts completely empty on every boot. No entity is ever seeded,
preloaded or hardcoded - every row is created by an API call.
"""
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: the logical clock starts at 2026-08-01T00:00:00Z on process start.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TS_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 UTC instant carrying a trailing Z. Returns aware dt."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = value[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000000")[:6]
        dt = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(microsecond=int(frac))
    else:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def date_of(ts_value):
    """The calendar date (YYYY-MM-DD) of an instant, read in UTC."""
    dt = parse_ts(ts_value)
    return dt.strftime("%Y-%m-%d") if dt else None


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.sites = {}
        self.food_types = {}
        self.recipes = {}
        self.stations = {}
        self.shifts = {}
        self.entries = {}
        self.baselines = {}
        self.targets = {}
        self.haulers = {}
        self.consignments = {}
        self.lines = {}
        self.tickets = {}
        self.alerts = {}
        self.findings = {}
        self.rollups = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return iso(self.clock)


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(**fields):
    """A row carrying the common fields: id, created_at, updated_at, version."""
    row = {
        "id": new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """PRD 2.7: a mutated row has updated_at refreshed and version incremented."""
    row["updated_at"] = db.now_iso()
    row["version"] = row["version"] + 1


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows):
    """Default list order: created_at ascending (insertion order as tie-break)."""
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)
