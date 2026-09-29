"""In-memory store, logical clock, identifier/timestamp minting.

Storage is process memory only: re-invoking start.sh wipes every byte of state.
Nothing here seeds, preloads or hardcodes an entity - the store boots empty and
every record is built by a caller through the declared endpoints.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

# PRD 2.4: "Until it is ever set, the clock reads 2026-08-01T00:00:00Z."
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "hatcheries",
    "waters",
    "brood_stocks",
    "spawn_events",
    "rearing_lots",
    "health_inspections",
    "stocking_requests",
    "allocation_plans",
    "transport_units",
    "stocking_events",
    "effluent_readings",
)

NOT_FOUND = {
    "hatcheries": "ERR_HATCHERY_NOT_FOUND",
    "waters": "ERR_WATER_NOT_FOUND",
    "brood_stocks": "ERR_BROOD_STOCK_NOT_FOUND",
    "spawn_events": "ERR_SPAWN_EVENT_NOT_FOUND",
    "rearing_lots": "ERR_LOT_NOT_FOUND",
    "health_inspections": "ERR_INSPECTION_NOT_FOUND",
    "stocking_requests": "ERR_REQUEST_NOT_FOUND",
    "allocation_plans": "ERR_PLAN_NOT_FOUND",
    "transport_units": "ERR_TRANSPORT_UNIT_NOT_FOUND",
    "stocking_events": "ERR_EVENT_NOT_FOUND",
}


class _Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = _Store()


def clock():
    return db.current_utc


def new_id():
    # PRD 2.7: a UUID with no type prefix of any kind.
    return str(uuid.uuid4())


def request_id():
    import random
    import string

    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


_FRACTION = re.compile(r"\.(\d+)")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant; raise ERR_INVALID_REQUEST on anything else."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Expected an ISO 8601 UTC timestamp.")
    text = value.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Expected an ISO 8601 UTC timestamp.")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"

    def _pad(match):
        digits = match.group(1)
        return "." + (digits + "000000")[:6]

    text = _FRACTION.sub(_pad, text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO 8601 UTC timestamp.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_instant(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.9 / 2.7)."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%s.%03dZ" % (moment.strftime("%Y-%m-%dT%H:%M:%S"), moment.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def days(count):
    return timedelta(days=count)


def hours(count):
    return timedelta(hours=count)


class Tx(object):
    """Collects the records an operation actually changed.

    PRD 2.7: every record the service changes gets exactly one `version` bump and
    a fresh `updated_at`; no record it merely reads does. Collecting the dirty set
    and settling it once keeps a cascade that reaches a record twice from
    advancing that record's version twice.
    """

    def __init__(self):
        self._dirty = []

    def touch(self, record):
        if record is None:
            return
        for existing in self._dirty:
            if existing is record:
                return
        self._dirty.append(record)

    def settle(self):
        stamp = fmt_instant(clock())
        for record in self._dirty:
            if "version" in record:
                record["version"] = record["version"] + 1
                record["updated_at"] = stamp
        self._dirty = []


def base_record(with_revision=True):
    record = {
        "id": new_id(),
        "created_at": fmt_instant(clock()),
        "_seq": db.next_seq(),
    }
    if with_revision:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def get_or_404(collection, identifier):
    table = getattr(db, collection)
    if not isinstance(identifier, str):
        raise ApiError(NOT_FOUND[collection])
    record = table.get(identifier)
    if record is None:
        raise ApiError(NOT_FOUND[collection])
    return record


def find(collection, identifier):
    if not isinstance(identifier, str):
        return None
    return getattr(db, collection).get(identifier)


def values(collection):
    return list(getattr(db, collection).values())


def insert(collection, record):
    getattr(db, collection)[record["id"]] = record
    return record


def sort_key(record):
    return (record["created_at"], record["_seq"])
