"""In-memory data store and the server logical clock.

Storage is Python dicts only: no SQLite, no files, no seed data. The store
starts empty on every boot; every entity is built through the declared API.

The logical clock starts at exactly 2026-09-01T00:00:00Z and is only ever
moved by POST /confection/_clock/set_current_utc. Business rules never read
wall-clock time. `created_at` / `updated_at` / meta timestamps are also taken
from the logical clock (the system "does not consult wall-clock time for any
business rule", and the lot_code tie-break after created_at presumes ties are
possible, which only a settable clock produces).
"""

import re
import uuid
from datetime import datetime, timezone

from errors import ApiError, ERR_INVALID_REQUEST

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        # entity tables, keyed by id
        self.programs = {}
        self.products = {}
        self.runs = {}
        self.retailers = {}
        self.commitments = {}
        self.shipments = {}
        self.claims = {}
        self.warehouses = {}
        self.lots = {}
        self.dispositions = {}
        self.contracts = {}
        self.reports = {}
        # deterministic sequences
        self.lot_seq = 0       # drives lot_code LOT-<zero-padded monotone seq>
        self.insert_seq = 0    # global insertion order tie-break after created_at
        # the logical clock
        self.clock = CLOCK_START


db = DB()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def next_seq():
    db.insert_seq += 1
    return db.insert_seq


def next_lot_code():
    db.lot_seq += 1
    return "LOT-%06d" % db.lot_seq


def ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z.

    Used for created_at / updated_at / api_request_timestamp, which PRD 2.4/2.2
    pin to three fractional digits.
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_ts3():
    """Current logical-clock instant in the 3-fractional-digit format."""
    return ts3(db.clock)


def fmt_instant(dt):
    """Normalized UTC instant for window fields and clock echoes.

    Whole-second instants render as 2027-01-05T00:00:00Z (matching the PRD's
    own rendering of the startup clock); sub-second instants keep three
    fractional digits.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts3(dt)


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def parse_dt(value, field):
    """Parse an ISO 8601 instant to an aware UTC datetime. Raises 400 on bad input."""
    if not isinstance(value, str) or isinstance(value, bool):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if not _ISO_RE.match(text):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "field '%s' is not a valid ISO 8601 datetime" % field)
    iso = text.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Every mutation increments version by exactly 1 and refreshes updated_at.

    PRD 2.4: version is "incremented by exactly 1 on every mutation, including
    system-driven mutations such as state advances, allocation, cascades, and
    computed-field updates that accompany a transition; reads never change
    version".
    """
    entity["version"] += 1
    entity["updated_at"] = now_ts3()
