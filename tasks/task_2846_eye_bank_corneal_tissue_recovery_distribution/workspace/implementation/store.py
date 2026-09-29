"""In-memory store, logical clock and time helpers.

The store starts completely empty on every boot; no entity is ever seeded.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

COLLECTIONS = (
    "donors",
    "screening_records",
    "serology_panels",
    "technicians",
    "recoveries",
    "tissues",
    "evaluations",
    "surgeons",
    "requests",
    "allocations",
    "shipments",
    "temperature_readings",
    "reports",
    "investigations",
)

DB = {name: {} for name in COLLECTIONS}

# The logical clock. PRD 2.4: it starts at exactly this instant on every boot and
# never consults real wall-clock time.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_STATE = {"clock": CLOCK_START, "seq": 0}


def reset():
    for name in COLLECTIONS:
        DB[name] = {}
    _STATE["clock"] = CLOCK_START
    _STATE["seq"] = 0


def now():
    return _STATE["clock"]


def set_clock(value):
    _STATE["clock"] = value


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------- time helpers

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def iso(dt):
    """Render an instant with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Strictly parse an ISO-8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str) or not ISO_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO-8601 UTC instant: %r" % (value,))
    try:
        base = datetime(
            int(value[0:4]),
            int(value[5:7]),
            int(value[8:10]),
            int(value[11:13]),
            int(value[14:16]),
            int(value[17:19]),
            int(value[20:23]) * 1000,
            tzinfo=timezone.utc,
        )
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO-8601 UTC instant: %r" % (value,))
    return base


def floor_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def floor_hours(start, end):
    return int((end - start).total_seconds() // 3600)


def floor_days(start, end):
    return int((end - start).total_seconds() // 86400)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def round_half_up(value):
    """Round a Decimal to a whole number of cents using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------- row bookkeeping


def base_row(with_version=True):
    stamp = now()
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Record one mutation of a row: refresh updated_at and bump version."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def by_created(rows):
    """Sibling iteration order: ascending created_at, never identifier order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def collection(name):
    return DB[name]


def values(name):
    return list(DB[name].values())


def sort_desc(rows, key):
    """Descending by key; the newest row wins a tie on the key."""
    return sorted(rows, key=lambda r: (key(r), r["_seq"]), reverse=True)


def sort_asc(rows, key):
    return sorted(rows, key=lambda r: (key(r), r["_seq"]))
