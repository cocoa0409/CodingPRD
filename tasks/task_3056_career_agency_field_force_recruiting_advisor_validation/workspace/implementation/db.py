"""In-memory data store for the Career Agency Field Force API.

Storage is process-local dictionaries keyed by id. Nothing is persisted to disk
and nothing is seeded: every dictionary starts empty in a fresh process, so
``start.sh`` re-invocation wipes every byte of state (PRD §2.5 mandate that the
store starts empty; the store owns no DATA, only the SYSTEM).
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from errors import err, ERR_INVALID_REQUEST

# ---------------------------------------------------------------------------
# Logical clock. PRD §2.5: startup default is exactly 2026-09-01T00:00:00Z;
# before any /_clock/set_current_utc call the clock reads that default and must
# never fall back to real wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


def ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.2)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000,)


def parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise err(ERR_INVALID_REQUEST, "empty timestamp")
        try:
            if s.endswith("Z") or s.endswith("z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "malformed timestamp: %s" % value)
    else:
        raise err(ERR_INVALID_REQUEST, "malformed timestamp: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:18].upper()


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # --- entity tables -------------------------------------------------
        self.district_offices = {}
        self.advisors = {}
        self.candidates = {}
        self.assessments = {}
        self.contracts = {}
        self.validation_periods = {}
        self.licenses = {}
        self.registrations = {}
        self.appointments = {}
        self.policies = {}
        self.joint_cases = {}
        self.credits = {}
        self.persistency = {}
        self.orphans = {}
        self._clock = parse_dt(CLOCK_DEFAULT)
        self._lock = threading.RLock()

    # -- clock -------------------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, value):
        self._clock = parse_dt(value)

    # -- generic row helpers ----------------------------------------------
    @staticmethod
    def insert(table, row, id_field="id"):
        if not row.get(id_field):
            row[id_field] = new_id()
        table[row[id_field]] = row
        return row

    # -- common field management (PRD §2.5) --------------------------------
    def stamp_create(self, row):
        now = ts(self.now())
        row["created_at"] = now
        row["updated_at"] = now
        row["version"] = 1
        return row

    def touch(self, row):
        """A mutation: refresh updated_at and advance version by exactly 1."""
        row["updated_at"] = ts(self.now())
        row["version"] = row.get("version", 1) + 1
        return row


db = Store()