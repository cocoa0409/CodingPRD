"""In-memory store.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here: every row is created by a client through the declared API.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

import config

TABLE_NAMES = [
    "facilities",
    "country_requirements",
    "sires",
    "genomic_evaluations",
    "health_tests",
    "collection_bookings",
    "ejaculates",
    "straw_lots",
    "export_certificates",
    "distributors",
    "tanks",
    "consignment_transfers",
    "customer_herds",
    "mating_recommendations",
]

DB = {name: {} for name in TABLE_NAMES}

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK, "seq": 0}
LOCK = threading.RLock()


# ---------------------------------------------------------------- clock ----
def clock():
    """The logical clock (PRD 2.5).  Never the host wall clock."""
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def clock_iso():
    return iso(_state["clock"])


# ------------------------------------------------------------ timestamps ----
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def plus_days(dt, days):
    return dt + timedelta(seconds=int(days) * config.DAY_SECONDS)


def wall_now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ ids ----
def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------- rows ------
def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_record(table, fields):
    rec = dict(fields)
    stamp = iso(wall_now())
    rec["id"] = new_id()
    rec["created_at"] = stamp
    rec["updated_at"] = stamp
    rec["version"] = 1
    rec["_seq"] = next_seq()
    DB[table][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and increment version (PRD 2.4)."""
    rec["updated_at"] = iso(wall_now())
    rec["version"] = int(rec["version"]) + 1
    return rec


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[table].get(row_id)


def rows(table):
    """All rows of a table ordered by created_at ascending (PRD 2.3)."""
    return sorted(DB[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def find(table, **kwargs):
    out = []
    for rec in rows(table):
        if all(rec.get(k) == v for k, v in kwargs.items()):
            out.append(rec)
    return out


def dt_of(value):
    """Parse a stored canonical instant, or a YYYY-MM-DD calendar date, into a datetime.

    A calendar date (`sample_date`, `birth_date`) is read as UTC midnight of that
    day, which is what every arithmetic in the PRD does with it.
    """
    if value is None:
        return None
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
