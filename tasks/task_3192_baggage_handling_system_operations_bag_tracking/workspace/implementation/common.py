"""Auth, request-shape helpers, pagination and misc shared utilities."""

from flask import request

from db import DB, iso, parse_iso
from errors import fail

ROLES = [
    "PlatformAdmin",
    "AcceptanceAgent",
    "SortationAgent",
    "Screener",
    "LoadAgent",
    "TransferAgent",
    "BaggageServiceAgent",
    "Passenger",
]

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


# ---------------------------------------------------------------- auth ------
def authenticate():
    """Return (user_id, role).  Runs first on every request."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE")


# ------------------------------------------------------------- payloads -----
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST")
    return payload


def require(payload, *names):
    for name in names:
        if name not in payload or payload[name] is None:
            fail("ERR_INVALID_REQUEST")


def enum_value(payload, name, allowed, required=True, allow_none=False):
    if name not in payload or payload[name] is None:
        if allow_none:
            return None
        if required:
            fail("ERR_INVALID_REQUEST")
        return None
    value = payload[name]
    if value not in allowed:
        fail("ERR_INVALID_ENUM_VALUE")
    return value


def number(payload, name, required=True):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST")
        return None
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST")
    return value


def integer(payload, name, required=True):
    value = number(payload, name, required=required)
    if value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        fail("ERR_INVALID_REQUEST")
    return int(value)


def boolean(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST")
    return value


def text(payload, name, required=True):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST")
        return None
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST")
    return value


def datetime_value(payload, name, required=True):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST")
        return None
    dt = parse_iso(payload[name])
    if dt is None:
        fail("ERR_INVALID_REQUEST")
    return dt


def version_token(payload, name):
    """The OCC token is a non-optional input field on the three guarded writes."""
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST")
    return value


# ----------------------------------------------------------- pagination -----
def paginate(rows, query):
    """Slice a collection for a list response.

    PRD §2.3: `limit` "is constrained to a minimum of 1 and a maximum of 100" —
    a value outside that range is refused as a malformed request.
    """
    raw_limit = query.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            fail("ERR_INVALID_REQUEST")
    try:
        offset = int(query.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }


def sort_by_creation(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def query_flag(name):
    """Parse a boolean-ish query filter; None when absent."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def clock():
    return DB.now()


def clock_iso():
    return iso(DB.now())