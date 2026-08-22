"""In-memory data store and the server-held logical clock.

Nothing is seeded here.  Every collection starts empty on every boot; the API
surface is the only way records come into existence.
"""
import itertools
import math
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

# PRD 2.5: before any client has moved it the logical clock reads exactly this.
INITIAL_LOGICAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "stations",
    "subcontractors",
    "flight_banks",
    "turns",
    "agents",
    "certifications",
    "gse_units",
    "turn_resources",
    "incidents",
    "billing_periods",
    "billing_lines",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = INITIAL_LOGICAL_CLOCK
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


# ---------------------------------------------------------------- datetimes
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not _ISO_RE.match(text):
        raise ValueError("bad iso instant")
    normalised = text.replace(" ", "T").replace("z", "Z")
    if normalised.endswith("Z"):
        normalised = normalised[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def now_stamp():
    """Server-stamped instant, taken from the logical clock (PRD 2.5)."""
    return format_iso(db.clock)


def as_dt(stored):
    """Parse a stored timestamp string back into a datetime."""
    if stored is None:
        return None
    if isinstance(stored, datetime):
        return stored
    return parse_iso(stored)


def whole_minutes_between(start, end):
    """Elapsed seconds divided by sixty, taken down to the next whole minute."""
    return int(math.floor((end - start).total_seconds() / 60.0))


def whole_days_between(start, end):
    return int(math.floor((end - start).total_seconds() / 86400.0))


def plus_minutes(moment, minutes):
    return moment + timedelta(minutes=minutes)


# ------------------------------------------------------------------ numbers
def rhu(value, places=0):
    """Round half up to `places` decimal places, in exact decimal arithmetic."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


def pct2(value):
    return rhu(value, 2)


def to_json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


# ------------------------------------------------------------------ records
def new_record(kind, fields):
    stamp = now_stamp()
    record = {"id": db.new_id()}
    record.update(fields)
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_kind"] = kind
    record["_seq"] = db.next_seq()
    return record


def serialize(record, extra=None):
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = to_json_value(value)
    if extra:
        for key, value in extra.items():
            out[key] = to_json_value(value)
    return out


def sort_key(record):
    return (record["created_at"], record["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)


def require(collection, record_id, entity):
    from errors import NOT_FOUND_BY_ENTITY
    if not isinstance(record_id, str) or record_id not in collection:
        raise ApiError(NOT_FOUND_BY_ENTITY[entity])
    return collection[record_id]
