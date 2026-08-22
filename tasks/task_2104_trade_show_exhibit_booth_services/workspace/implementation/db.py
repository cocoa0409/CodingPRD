"""In-memory data store, the logical show clock, id / timestamp helpers.

The store starts EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Every entity a test needs is built through the declared API surface.
"""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.4 — before any operator repositions it the logical clock reads exactly this.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """Every entity table. Instantiated empty; never seeded."""

    def __init__(self):
        self.venues = {}
        self.jurisdictions = {}
        self.warehouses = {}
        self.shows = {}
        self.exhibitors = {}
        self.booths = {}
        self.assets = {}
        self.designs = {}
        self.service_orders = {}
        self.order_lines = {}
        self.crates = {}
        self.shipments = {}
        self.labor_calls = {}
        self.change_orders = {}
        self.invoices = {}
        self.claims = {}
        self.refurbs = {}
        self.licenses = {}


store = Store()


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------

def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(dt):
    """Canonical ISO 8601 UTC rendering with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class LogicalClock:
    """The single logical clock every temporal rule in the system reads."""

    def __init__(self):
        self.iso = DEFAULT_CLOCK_ISO
        self.dt = parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso_text):
        self.dt = parse_iso(iso_text)
        self.iso = iso_text

    def now(self):
        return self.dt

    def stamp(self):
        """The instant to persist on a logical-clock stamped field."""
        return self.iso


clock = LogicalClock()


def now_dt():
    return clock.now()


def now_stamp():
    return clock.stamp()


# --------------------------------------------------------------------------
# identity / audit helpers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def wall_now():
    """Strictly increasing wall-clock ISO 8601 UTC stamp, three fractional digits.

    Used only for the audit triple (created_at / updated_at), never for a
    business rule: every business rule reads the logical clock above.
    """
    current = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and current <= last:
        current = last + timedelta(milliseconds=1)
    _wall_last[0] = current
    return iso_utc(current)


def stamp_common(entity):
    """Stamp the audit triple on a freshly created row."""
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next(_seq_counter)
    return entity


def touch(entity):
    """A mutation of the row: refresh updated_at and advance version by one."""
    entity["updated_at"] = wall_now()
    entity["version"] = int(entity.get("version", 1)) + 1
    return entity


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
