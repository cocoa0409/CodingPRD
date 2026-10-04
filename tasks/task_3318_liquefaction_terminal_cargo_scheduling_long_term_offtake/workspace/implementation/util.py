"""Shared helpers: ids, timestamps, auth, body validation, entity touch."""
import uuid
from datetime import datetime, timezone, timedelta

from flask import request

import db
from errors import fail

ROLES = {"TerminalOperator", "CommercialManager", "GasScheduler", "MarineScheduler", "CustomerRep"}
ALL_ROLES = sorted(ROLES)


def new_id():
    return str(uuid.uuid4())


def logical_now_iso():
    """Logical-clock timestamp used for system-stamped fields.

    PRD §2.4 pins the startup default clock to the exact string
    `2026-09-01T00:00:00Z`; when the logical clock carries no sub-second
    component, render without fractional digits so system-stamped values
    (cancelled_at, departed_at, shifted window bounds, ...) match the
    clock's own representation. Non-zero sub-seconds keep 3 fractional
    digits per §2.5/§2.6.
    """
    dt = db.get_clock()
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = logical_now_iso()
    entity["version"] = entity.get("version", 0) + 1


def stamp_new(entity):
    entity["id"] = new_id()
    now = logical_now_iso()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def auth():
    """Validate X-User-Role / X-User-ID. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_FORBIDDEN", "Role not allowed for this endpoint")


def body():
    """JSON body, tolerant of missing/invalid JSON -> treated as {} for GET-less posts."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---- typed field extraction (ERR_INVALID_REQUEST on violation) ----

def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        fail("ERR_INVALID_REQUEST", f"{name} is required and must be a non-empty string")
    return v


def opt_str(data, name, default=None):
    v = data.get(name, default)
    if v is not None and not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", f"{name} must be a string")
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(data, name, min_value=None):
    v = data.get(name)
    if not _is_int(v):
        fail("ERR_INVALID_REQUEST", f"{name} is required and must be an integer")
    if min_value is not None and v < min_value:
        fail("ERR_INVALID_REQUEST", f"{name} must be >= {min_value}")
    return v


def req_num(data, name, min_value=None, min_exclusive=False, max_value=None):
    v = data.get(name)
    if not _is_num(v):
        fail("ERR_INVALID_REQUEST", f"{name} is required and must be a number")
    if min_value is not None:
        if min_exclusive and not v > min_value:
            fail("ERR_INVALID_REQUEST", f"{name} must be > {min_value}")
        if not min_exclusive and v < min_value:
            fail("ERR_INVALID_REQUEST", f"{name} must be >= {min_value}")
    if max_value is not None and v > max_value:
        fail("ERR_INVALID_REQUEST", f"{name} must be <= {max_value}")
    return v


def req_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"{name} is required and must be a boolean")
    return v


def parse_dt(value, field):
    """Parse ISO-8601 datetime to aware UTC datetime."""
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        fail("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", f"{field} must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", f"{field} must be a YYYY-MM-DD date string")


def dt_to_iso(dt):
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def pub(entity):
    """Public view of a stored entity: strip internal underscore-prefixed keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
