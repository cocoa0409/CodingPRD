"""In-memory data store, logical harbor clock, id and timestamp minting.

Storage is process-local Python dicts only.  Nothing is seeded at import or at
boot: every row a test needs is built through the declared API surface.
"""

import random
import string
import threading
import time
import uuid
from datetime import datetime, timezone, date

# ---------------------------------------------------------------- timestamps

_ts_lock = threading.Lock()
_last_ms = [0]


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_instant(dt):
    """ISO 8601 UTC; fractional digits only when the instant carries them."""
    if dt.microsecond:
        return iso_ms(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def now_stamp():
    """Wall-clock creation/update stamp, strictly increasing at ms resolution."""
    with _ts_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms[0]:
            ms = _last_ms[0] + 1
        _last_ms[0] = ms
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return iso_ms(dt)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------- parsing

def parse_instant(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime truncated to
    whole seconds (PRD 2.6: instants are compared at whole-second resolution)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(microsecond=0)


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def date_str(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# ---------------------------------------------------------------- the store

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.docks = {}
        self.stops = {}
        self.vessels = {}
        self.inspections = {}
        self.crew = {}
        self.service_days = {}
        self.trips = {}
        self.dock_slots = {}
        self.ride_passes = {}
        self.bookings = {}
        self.interruptions = {}
        self.claims = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    # -- clock -------------------------------------------------------------
    def clock_now(self):
        return self.clock

    def clock_date(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt

    # -- row helpers -------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, versioned=True):
        stamp = now_stamp()
        row = {
            "id": new_id(),
            "created_at": stamp,
            "_seq": self.next_seq(),
        }
        if versioned:
            row["updated_at"] = stamp
            row["version"] = 1
        return row

    def touch(self, row):
        row["updated_at"] = now_stamp()
        row["version"] = row.get("version", 1) + 1
        return row

    # -- ordered scans -----------------------------------------------------
    @staticmethod
    def ordered(rows):
        return sorted(rows, key=lambda r: r["_seq"])


store = Store()
