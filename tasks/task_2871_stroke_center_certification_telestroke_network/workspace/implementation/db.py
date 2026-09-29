"""In-memory data store, the logical UTC clock, and record bookkeeping.

The store starts EMPTY on every boot: no entity is seeded, preloaded or
hardcoded anywhere.  Everything is created through the declared API surface.
"""
import itertools
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from constants import DEFAULT_CLOCK_RAW

COLLECTIONS = (
    "centers",
    "agreements",
    "neurologists",
    "cases",
    "consults",
    "checklists",
    "transfers",
    "deviations",
    "abstractions",
    "reports",
)

DB = {name: {} for name in COLLECTIONS}

_seq_counter = itertools.count(1)

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([Zz]|[+-]\d{2}:?\d{2})$"
)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_RE.match(text):
        return None
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    # datetime.fromisoformat tolerates at most 6 fractional digits
    frac = re.search(r"\.(\d+)", text)
    if frac and len(frac.group(1)) > 6:
        text = text[: frac.start(1) + 6] + text[frac.end(1):]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class _Clock(object):
    """The server-held logical UTC clock.  Wall-clock time is never read."""

    def __init__(self):
        self.raw = DEFAULT_CLOCK_RAW
        self.dt = parse_iso(DEFAULT_CLOCK_RAW)

    def set(self, raw):
        parsed = parse_iso(raw)
        self.raw = raw
        self.dt = parsed


CLOCK = _Clock()


def reset_store():
    for name in COLLECTIONS:
        DB[name].clear()
    CLOCK.raw = DEFAULT_CLOCK_RAW
    CLOCK.dt = parse_iso(DEFAULT_CLOCK_RAW)


def now_dt():
    return CLOCK.dt


def now_raw():
    """The logical clock rendered exactly as it was supplied to the server."""
    return CLOCK.raw


def now_millis():
    """The logical clock with three fractional digits (PRD 2.2)."""
    dt = CLOCK.dt
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def request_id():
    import random
    import string

    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --- record bookkeeping -----------------------------------------------------

def _touched():
    from flask import g

    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def insert(collection, record):
    record["id"] = new_id()
    record["created_at"] = now_raw()
    record["updated_at"] = now_raw()
    record["version"] = 1
    record["_seq"] = next(_seq_counter)
    DB[collection][record["id"]] = record
    # a freshly created row is already at version 1 for this request
    _touched().add(record["id"])
    return record


def touch(record):
    """Refresh updated_at and bump version once per request per record."""
    seen = _touched()
    if record["id"] in seen:
        record["updated_at"] = now_raw()
        return record
    seen.add(record["id"])
    record["updated_at"] = now_raw()
    record["version"] = record["version"] + 1
    return record


def setf(record, field, value):
    """Assign a field, touching the record only when the value really moves."""
    if record.get(field) != value:
        record[field] = value
        touch(record)
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return DB[collection].get(record_id)


def all_of(collection):
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


# --- numeric helpers --------------------------------------------------------

def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q1(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def q0(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def clamp_0_100(value):
    if value < Decimal("0"):
        return Decimal("0")
    if value > Decimal("100"):
        return Decimal("100")
    return value


def elapsed_seconds(start, end):
    return int((end - start).total_seconds())


def floor_minutes(start, end):
    seconds = elapsed_seconds(start, end)
    return seconds // 60
