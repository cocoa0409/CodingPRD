"""In-memory data store, logical clock, id and timestamp helpers.

The store is EMPTY on every boot.  Nothing here seeds, preloads or hardcodes
any entity: every row is created by a client through the declared endpoints.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# The logical clock's fixed starting instant (PRD 2.5).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

DB = {
    "brewery": None,
    "beers": {},
    "tanks": {},
    "batches": {},
    "runs": {},
    "kegs": {},
    "pours": {},
    "licenses": {},
    "appointments": {},
    "orders": {},
    "reports": {},
    "permits": {},
}

_CLOCK = {"now": CLOCK_EPOCH}
_SEQ = {"n": 0}


def reset():
    DB["brewery"] = None
    for key in ("beers", "tanks", "batches", "runs", "kegs", "pours",
                "licenses", "appointments", "orders", "reports", "permits"):
        DB[key] = {}
    _CLOCK["now"] = CLOCK_EPOCH
    _SEQ["n"] = 0


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

def clock_now():
    return _CLOCK["now"]


def set_clock(instant):
    _CLOCK["now"] = instant
    return _CLOCK["now"]


def clock_now_str():
    return fmt_dt(clock_now())


# --------------------------------------------------------------------------
# identity, sequencing and timestamps
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def audit_now():
    """Wall-clock stamp used for created_at / updated_at audit fields."""
    return fmt_dt(datetime.now(UTC))


def plus_days(instant, days):
    return instant + timedelta(days=int(days))


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(fields, versioned=True):
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = audit_now()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Register a mutation: refresh updated_at and bump version by exactly 1."""
    if row is None:
        return None
    row["updated_at"] = audit_now()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(rows):
    return sorted(rows, key=sort_key)


def all_rows(collection):
    return ordered(list(DB[collection].values()))


def brewery():
    return DB["brewery"]
