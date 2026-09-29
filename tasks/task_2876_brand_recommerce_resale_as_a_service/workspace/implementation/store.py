"""In-memory storage, the logical clock, and row bookkeeping.

Storage is plain Python dicts held in this process only.  Nothing is seeded,
preloaded or persisted: a fresh interpreter starts with every table empty and
every entity is created by callers through the declared endpoints.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError, NOT_FOUND_FOR

# PRD 2.4: before any client has set it the logical clock reads exactly this
# instant, and it never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK}
_seq = itertools.count(1)

TABLE_NAMES = (
    "customers",
    "grade_policies",
    "credit_policies",
    "store_locations",
    "refurb_bays",
    "channels",
    "trade_ins",
    "credit_grants",
    "ledger_entries",
    "resale_units",
    "refurb_orders",
    "refurb_tasks",
    "markdown_campaigns",
    "resale_orders",
    "diversion_reports",
)

TABLES = {name: {} for name in TABLE_NAMES}


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# ISO 8601 UTC, millisecond precision (PRD 2.4 / 2.6)
# --------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
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


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?"
    r"(([Zz])|([+-]\d{2}:?\d{2}))?$"
)


def parse_ts(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or not _ISO_RE.match(raw):
        return None
    text = raw.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def create(table_name, fields, versioned=True):
    """Insert a row.  ``versioned`` False is the append-only shape of PRD 2.6:
    only ``id`` and ``created_at``, no ``updated_at`` and no ``version``."""
    row = {"id": new_id()}
    row.update(fields)
    stamp = now()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next(_seq)
    row["_kind"] = table_name
    TABLES[table_name][row["id"]] = row
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by exactly one."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def rows(table_name):
    return list(TABLES[table_name].values())


def sort_key(row):
    return (row["created_at"], row["_seq"])


def ordered(collection):
    return sorted(collection, key=sort_key)


def get(table_name, row_id):
    if not isinstance(row_id, str):
        return None
    return TABLES[table_name].get(row_id)


def require(table_name, row_id):
    row = get(table_name, row_id)
    if row is None:
        raise ApiError(NOT_FOUND_FOR[table_name])
    return row


# --------------------------------------------------------------------------
# policy lookups (PRD 2.7)
# --------------------------------------------------------------------------
def active_grade_policy(product_category, condition_grade):
    if product_category is None or condition_grade is None:
        return None
    found = [
        p
        for p in rows("grade_policies")
        if p["status"] == "ACTIVE"
        and p["product_category"] == product_category
        and p["condition_grade"] == condition_grade
    ]
    if not found:
        return None
    return ordered(found)[-1]


def active_credit_policy():
    found = [p for p in rows("credit_policies") if p["status"] == "ACTIVE"]
    if not found:
        return None
    return ordered(found)[-1]
