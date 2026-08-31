"""In-memory store, logical clock, id/timestamp minting.

Storage is process-local Python dicts only.  A fresh process starts with a
completely empty store -- nothing is ever seeded, preloaded or hardcoded.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"

_LOCK = threading.RLock()


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.payers = {}
        self.patients = {}
        self.providers = {}
        self.contracts = {}
        self.vehicles = {}
        self.episodes = {}
        self.screenings = {}
        self.barriers = {}
        self.referrals = {}
        self.offers = {}
        self.authorizations = {}
        self.orders = {}
        self.clock = parse_dt(DEFAULT_CLOCK_RAW)
        self.clock_raw = DEFAULT_CLOCK_RAW
        self._seq = 0
        self._last_ms = 0

    # ---- clock -----------------------------------------------------------
    def now(self):
        """The logical clock (never the host wall clock)."""
        return self.clock

    def now_raw(self):
        """The logical clock rendered exactly as it was supplied."""
        return self.clock_raw

    def now_iso(self):
        """The logical clock instant rendered in the house timestamp format --
        an ISO 8601 UTC timestamp with three fractional digits (PRD 2.4).
        Every row field that records "the logical clock instant" uses this,
        so the rendering never depends on how an operator happened to spell
        the instant when setting the clock."""
        return fmt_dt(self.clock)

    def set_clock(self, dt, raw):
        self.clock = dt
        self.clock_raw = raw

    # ---- row minting -----------------------------------------------------
    def next_seq(self):
        with _LOCK:
            self._seq += 1
            return self._seq

    def wall_now_iso(self):
        """Strictly increasing wall-clock ISO timestamp with millisecond
        precision -- used for created_at / updated_at so that creation order
        is always strictly ascending."""
        with _LOCK:
            now = datetime.now(timezone.utc)
            ms = int(now.timestamp() * 1000)
            if ms <= self._last_ms:
                ms = self._last_ms + 1
            self._last_ms = ms
            dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            return fmt_dt(dt)


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_row():
    ts = db.wall_now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Record a mutation: bump version, refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.wall_now_iso()
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (stable by mint order)."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def add_days(dt, days):
    return dt + timedelta(days=days)
