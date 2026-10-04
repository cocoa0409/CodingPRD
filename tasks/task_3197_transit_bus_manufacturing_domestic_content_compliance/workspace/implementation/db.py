"""In-memory data store plus the logical clock.

The store starts empty on every boot; the harness restarts the server per test.
"""
from datetime import datetime, timezone, timedelta
import uuid
import itertools

# Logical clock: initial value pinned by PRD 2.4.
_INITIAL_CLOCK = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    """Parse ISO 8601 to aware datetime (UTC). Accepts trailing Z and fractional seconds."""
    if isinstance(s, datetime):
        return s
    t = str(s).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_logical(dt):
    """Format a datetime for business timestamps (logical-clock driven)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        frac = f"{dt.microsecond:06d}".rstrip("0")
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "." + frac + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def fmt_ts(dt):
    """Format wall-clock timestamps (created_at etc.) with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


class Clock:
    def __init__(self):
        self._now = _parse_iso(_INITIAL_CLOCK)

    def now(self):
        return self._now

    def now_iso(self):
        return _fmt_logical(self._now)

    def set(self, iso_str):
        self._now = _parse_iso(iso_str)
        return self._now


class Store:
    def __init__(self):
        self.clock = Clock()
        self.seq = itertools.count(1)
        self.agencies = {}
        self.contracts = {}
        self.option_orders = {}
        self.configurations = {}
        self.components = {}
        self.certificates = {}
        self.audits = {}
        self.slots = {}
        self.kits = {}
        self.buses = {}
        self.inspections = {}
        self.claims = {}
        self.trainings = {}
        self.stocks = {}
        self.serial_counter = itertools.count(1)

    def next_serial(self):
        return "SN-%08d" % next(self.serial_counter)


DB = Store()


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def stamp_new(rec, common=True):
    rec["id"] = new_id()
    rec["created_at"] = fmt_ts(wall_now())
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next(DB.seq)
    return rec


def touch(rec):
    rec["updated_at"] = fmt_ts(wall_now())
    rec["version"] = rec.get("version", 1) + 1
