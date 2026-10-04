"""Logical clock, in-memory store, timestamp/rounding helpers and response envelope.

Storage is in-memory only: the dicts below start empty in every fresh process and
nothing is ever seeded, preloaded or written to disk.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, fail

# ---------------------------------------------------------------------------
# Logical clock -- PRD 2.4: reads 2026-09-01T00:00:00Z before any clock call and
# never falls back to the machine's real time.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

CLOCK = {"now": DEFAULT_CLOCK}

# Monotonic creation counter, used only to make list ordering total when two rows
# share a created_at instant on the logical clock.
SEQ = {"n": 0}

# ---------------------------------------------------------------------------
# In-memory store -- one dict per entity, keyed by id. Empty on every boot.
# ---------------------------------------------------------------------------

DB = {
    "incidents": {},
    "assessments": {},
    "field_kitchens": {},
    "partner_kitchens": {},
    "meal_orders": {},
    "suppliers": {},
    "ingredient_purchases": {},
    "distribution_sites": {},
    "distribution_runs": {},
    "distribution_stops": {},
    "donor_commitments": {},
}


def now():
    return CLOCK["now"]


def new_id():
    """Server-minted UUID string: no type prefix, no entity marker (PRD 2.4)."""
    return str(uuid.uuid4())


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


# ---------------------------------------------------------------------------
# Timestamps: ISO 8601 UTC with exactly three fractional digits (PRD 2.4).
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Timestamp value is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_bucket(dt):
    """UTC calendar-day key of an instant (half-open [00:00:00Z, 24:00:00Z))."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.date()


def hours_later(hours):
    return now() + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Money / integer arithmetic -- half-up rounding, never float for currency.
# ---------------------------------------------------------------------------

def dec(value):
    return Decimal(str(value))


def round_half_up(value):
    """Round half away from zero to an integer (PRD 2.7)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_round(numerator, denominator):
    if denominator == 0:
        return 0
    return round_half_up(dec(numerator) * dec(100) / dec(denominator))


# ---------------------------------------------------------------------------
# Row helpers -- any change to a row refreshes updated_at and bumps version
# (PRD 2.4: recomputations and cascades mutate the rows they touch).
# ---------------------------------------------------------------------------

def make_row(**fields):
    t = now()
    row = dict(fields)
    row["id"] = new_id()
    row["_seq"] = next_seq()
    row["created_at"] = t
    row["updated_at"] = t
    row["version"] = 1
    return row


def touch(row, at=None):
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = at or now()
    return True


def assign(row, key, value, at=None):
    """Store value; bump updated_at/version only when it actually changed."""
    if row.get(key) != value:
        row[key] = value
        touch(row, at)
        return True
    return False


def set_always(row, key, value, at=None):
    row[key] = value
    touch(row, at)
    return True


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2 / SCAFFOLD response_envelope)
#   success: { meta:{api_request_id, api_request_timestamp[, pagination]},
#              response_type: "object"|"array", data: ... }
#   error:   { meta:{api_request_id, api_request_timestamp},
#              response_type: "error", data:{error_id, message} }
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=16))


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def envelope(data, response_type="object", pagination=None):
    return {"meta": _meta(pagination), "response_type": response_type, "data": data}


def error_envelope(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items, limit, offset):
    """Slice a list and build the four pagination fields of `meta` (PRD 2.3)."""
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------

def sort_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def serialize(row):
    """Strip internal bookkeeping keys before a row leaves the server."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
