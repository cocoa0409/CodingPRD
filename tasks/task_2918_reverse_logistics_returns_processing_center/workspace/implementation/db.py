"""In-memory data store and the logical UTC clock.

Every table starts empty on every boot; nothing is ever seeded here.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

EPOCH_START = "2026-08-01T00:00:00.000Z"

TABLE_NAMES = (
    "clients",
    "catalog_items",
    "processing_bays",
    "channels",
    "rmas",
    "rma_lines",
    "receipts",
    "return_lines",
    "fraud_checks",
    "work_orders",
    "disposition_orders",
    "refund_releases",
    "pricing_feedback",
    "shrink_ledger_entries",
)

lock = threading.RLock()

tables = {}
_seq = {"n": 0}
_clock = {"now": None}


def reset():
    for name in TABLE_NAMES:
        tables[name] = {}
    _seq["n"] = 0
    _clock["now"] = parse_instant(EPOCH_START)


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- time helpers

def parse_instant(text):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    """Render an aware datetime as an ISO-8601 UTC instant with 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now():
    return _clock["now"]


def now_str():
    return fmt_instant(_clock["now"])


def set_now(dt):
    _clock["now"] = dt.astimezone(timezone.utc)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


# ------------------------------------------------------------- row primitives

def insert(table, row):
    row["_seq"] = next_seq()
    tables[table][row["id"]] = row
    return row


def get(table, key):
    if not isinstance(key, str):
        return None
    return tables[table].get(key)


def all_rows(table):
    return list(tables[table].values())


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def touch(row):
    """Refresh updated_at and advance version by exactly one."""
    row["updated_at"] = now_str()
    row["version"] = row.get("version", 1) + 1
    return row


def stamp_new(row, versioned=True):
    ts = now_str()
    row["created_at"] = ts
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    return row


reset()
