"""In-memory data store, id/timestamp minting and the logical clock.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded here: every row is built by a client through a declared endpoint.
"""

import datetime
import itertools
import random
import string
import uuid

# --- collections -----------------------------------------------------------
standards = {}
definitions = {}
properties = {}
units = {}
inspections = {}
selections = {}
deficiencies = {}
sweeps = {}
work_orders = {}
appeals = {}
plans = {}
capital_items = {}

_seq = itertools.count(1)

# --- the logical clock -----------------------------------------------------
# Before any client sets it the logical clock reads exactly
# 2026-08-01T00:00:00Z and it never falls back to real wall-clock time.
LOGICAL_CLOCK_EPOCH = datetime.datetime(
    2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
)
_clock = {"now": LOGICAL_CLOCK_EPOCH}


def logical_now():
    return _clock["now"]


def set_logical_now(value):
    _clock["now"] = value


# --- instants --------------------------------------------------------------
def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def wall_now():
    return datetime.datetime.now(datetime.timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --- row lifecycle ---------------------------------------------------------
def stamp_new(row):
    """Attach the four system-managed common properties to a fresh row."""
    now = fmt_instant(wall_now())
    row["id"] = new_id()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = next(_seq)
    return row


def touch(row, bump_version=True):
    row["updated_at"] = fmt_instant(wall_now())
    if bump_version:
        row["version"] = row["version"] + 1
    return row


def public(row):
    """Strip internal bookkeeping keys from a row for serialisation."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
