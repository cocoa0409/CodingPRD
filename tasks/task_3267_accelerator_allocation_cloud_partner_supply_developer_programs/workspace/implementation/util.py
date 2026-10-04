"""Clock, identifier, rounding and request-shape helpers."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN

from constants import (
    DEFAULT_CLOCK_UTC,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from error import CatalogError, ERR_INVALID_REQUEST

_ALNUM = string.ascii_uppercase + string.digits


# ------------------------------------------------------------- identifiers --
def new_id():
    """A server-minted UUID with no type prefix (PRD 2.10)."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(18))


# ------------------------------------------------------------------- clock --
def parse_utc(value):
    """Parse an ISO 8601 instant, tolerating a trailing Z and no offset."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise CatalogError(ERR_INVALID_REQUEST, "current_utc is not an ISO 8601 instant.")
    else:
        raise CatalogError(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 string.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def initial_clock():
    return parse_utc(DEFAULT_CLOCK_UTC)


def format_utc(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03dZ" % (dt.microsecond // 1000)
    )


def days_between(later, earlier):
    """Whole days from `earlier` to `later`, truncated toward zero."""
    return int((later - earlier).total_seconds()) // 86400


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------- rounding ---
def q(value, places=0):
    """Round half-even to `places` decimals and return a float."""
    exp = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(exp, rounding=ROUND_HALF_EVEN))


def qi(value):
    """Round half-even to a whole number and return an int."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def floor_div(a, b):
    return a // b


def ceil_div(a, b):
    return -((-a) // b)


# ------------------------------------------------------------ body parsing --
def body_of(payload):
    return payload if isinstance(payload, dict) else {}


def require(body, key, kind="string", positive=False, allow_zero=True):
    """Fetch a required body field, or raise ERR_INVALID_REQUEST."""
    if key not in body or body[key] is None:
        raise CatalogError(ERR_INVALID_REQUEST, "Missing required field '%s'." % key)
    value = body[key]
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must be an integer." % key)
        if positive and value <= 0:
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must be strictly positive." % key)
        if not positive and not allow_zero and value < 0:
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must not be negative." % key)
        if value < 0:
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must not be negative." % key)
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must be numeric." % key)
        if value < 0:
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must not be negative." % key)
    elif kind == "bool":
        if not isinstance(value, bool):
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must be a boolean." % key)
    elif kind == "list":
        if not isinstance(value, list):
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must be an array." % key)
    else:
        if not isinstance(value, str) or value == "":
            raise CatalogError(ERR_INVALID_REQUEST, "'%s' must be a non-empty string." % key)
    return value


def optional(body, key, default=None, kind="string"):
    if key not in body or body[key] is None:
        return default
    return body[key]


def require_enum(value, allowed, field):
    if value not in allowed:
        raise CatalogError(ERR_INVALID_REQUEST, "'%s' has unknown member '%s'." % (field, value))
    return value


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)


# -------------------------------------------------------------- pagination --
def paginate(items, query):
    """Slice a list per the scaffold's limit/offset contract and report meta."""
    raw_limit = query.get("limit")
    raw_offset = query.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise CatalogError(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise CatalogError(ERR_INVALID_REQUEST, "limit must lie between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise CatalogError(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise CatalogError(ERR_INVALID_REQUEST, "offset must not be negative.")
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, meta


def by_created(items):
    """Default list ordering: creation timestamp ascending (PRD 2.3).

    The mint sequence is the tie-break so that resources created within one
    logical instant still list in creation order.
    """
    return sorted(items, key=lambda row: (row.get("created_at", ""), row.get("_seq", 0)))