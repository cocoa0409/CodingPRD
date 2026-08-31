"""In-memory store, logical clock and time helpers.

Nothing here is seeded: every collection starts empty on every boot and is
populated exclusively by API calls.
"""
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, NOT_FOUND

EPOCH_DEFAULT = "2026-08-01T00:00:00.000Z"

COLLECTIONS = (
    "engagements",
    "system_descriptions",
    "boundary_components",
    "trust_criteria",
    "controls",
    "criteria_mappings",
    "evidence_requests",
    "gaps",
    "audit_samples",
    "audit_exceptions",
    "subservice_organizations",
    "cuecs",
    "report_distributions",
    "bridge_letters",
    "customer_questionnaires",
)

DB = {name: {} for name in COLLECTIONS}

_STATE = {"clock": None, "seq": 0}


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO-8601 UTC instant. Returns a tz-aware datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    if _STATE["clock"] is None:
        _STATE["clock"] = parse_iso(EPOCH_DEFAULT)
    return _STATE["clock"]


def now_iso():
    return fmt_iso(now_dt())


def set_clock(dt):
    _STATE["clock"] = dt


def add_days(dt, days):
    from datetime import timedelta

    return dt + timedelta(seconds=86400 * days)


def floor_days(later, earlier):
    """floor((later - earlier) / 86400 seconds) as an integer."""
    delta = (later - earlier).total_seconds()
    return int(math.floor(delta / 86400.0))


# --------------------------------------------------------------------------
# decimal helpers
# --------------------------------------------------------------------------
def d(value):
    return Decimal(str(value))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def num2(value):
    return float(round_half_up(value, 2))


def num4(value):
    return float(round_half_up(value, 4))


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------
def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def new_row(collection, fields, versioned=True):
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    DB[collection][row["id"]] = row
    return row


def touch(row):
    """Register a real mutation of the row: refresh updated_at, bump version."""
    if "updated_at" in row:
        row["updated_at"] = now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def stamp(row):
    """Register a derived-counter refresh: no version bump."""
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def get_or_404(collection, row_id):
    if not isinstance(row_id, str):
        raise ApiError(NOT_FOUND[collection])
    row = DB[collection].get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def rows(collection):
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))
