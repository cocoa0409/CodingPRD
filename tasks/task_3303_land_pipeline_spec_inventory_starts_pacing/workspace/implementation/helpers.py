"""Common helpers: auth, idempotency, validation, resource plumbing."""

import json
import re
import uuid
from datetime import datetime, timezone

from flask import request

from db import db, now_wall, iso3
from errors import ApiError

ROLES = {
    "DIVISION_PRESIDENT",
    "LAND_MANAGER",
    "COMMUNITY_MANAGER",
    "SALES_AGENT",
    "TRADE_PARTNER",
}


def auth():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role header missing or invalid")
    return role, request.headers.get("X-User-ID")


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


def body():
    if request.method == "POST" and not request.data:
        return {}
    try:
        b = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Malformed JSON body")
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return b


def idem_begin():
    """Priority 2-3: Idempotency-Key presence, then replay consistency."""
    key = request.headers.get("Idempotency-Key")
    if key is None:
        raise ApiError("ERR_MISSING_IDEMPOTENCY_KEY", 400, "Idempotency-Key header required")
    raw = request.get_data(cache=True) or b""
    fp = raw.decode("utf-8", "replace")
    stored = db.idempotency.get(key)
    if stored is not None:
        if stored["fingerprint"] != fp:
            raise ApiError(
                "ERR_IDEMPOTENCY_REPLAY_MISMATCH", 409,
                "Idempotency-Key reused with a different request body",
            )
        return stored
    return {"key": key, "fingerprint": fp}


def idem_store(ctx, status, body_text):
    if "key" in ctx:
        db.idempotency[ctx["key"]] = {
            "fingerprint": ctx["fingerprint"],
            "status": status,
            "body": body_text,
        }


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _valid_type(value, typ):
    if typ == "string":
        return isinstance(value, str)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "datetime":
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False
    return True


def require_fields(b, specs):
    """specs: list of (name, type, allowed_enum_or_None, nullable)."""
    for name, typ, allowed, nullable in specs:
        if name not in b:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {name}")
        v = b[name]
        if v is None:
            if not nullable:
                raise ApiError("ERR_VALIDATION", 400, f"Field {name} may not be null")
            continue
        if not _valid_type(v, typ):
            raise ApiError("ERR_VALIDATION", 400, f"Field {name} has invalid type")
        if allowed is not None and v not in allowed:
            raise ApiError("ERR_VALIDATION", 400, f"Field {name} has invalid value")


def opt_string(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be a string")
    return v


def opt_integer(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be an integer")
    return v


def opt_boolean(b, name, default=False):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be a boolean")
    return v


def dt_field(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be an ISO 8601 string")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} is not a valid datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Resource plumbing
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def fresh_row():
    # PRD §2.4: "Time inside the system is not wall time. A single logical
    # clock governs every temporal rule" -- and "never falls back to wall
    # time". created_at feeds starts_this_period and cycle_time_days, both
    # logical-clock computations, so rows are stamped with the logical clock.
    ts = iso3(db.clock)
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(row, bump=True):
    row["updated_at"] = iso3(db.clock)
    if bump:
        row["version"] = row.get("version", 1) + 1


def get_or_404(store, rid):
    row = store.get(rid)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return row


def clock():
    return db.clock


def dt_or_none(s):
    if s is None:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_or_none(d):
    if d is None:
        return None
    return iso3(d)
