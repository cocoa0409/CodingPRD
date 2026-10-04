"""Auth middleware and request validation helpers (pipeline order per PRD §2.8)."""
import re
from flask import request

import db
from errors import err

ROLES = {"Talent", "Buyer", "Moderator", "PlatformAdmin"}


def authenticate():
    """Step 1: auth headers present and role recognized."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "missing or malformed X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(role, allowed):
    """Step 2: RBAC check."""
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED",
                  "role %s not permitted for this endpoint" % role)


def get_json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "request body must be JSON")
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Field validation helpers (step 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def req_str(body, field, min_len=None, max_len=None):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "field '%s' is required and must be a string" % field)
    if min_len is not None and len(v) < min_len:
        raise err("ERR_INVALID_REQUEST", "field '%s' is too short" % field)
    if max_len is not None and len(v) > max_len:
        raise err("ERR_INVALID_REQUEST", "field '%s' is too long" % field)
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "field '%s' is required and must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err("ERR_INVALID_REQUEST", "field '%s' below minimum" % field)
    if max_v is not None and v > max_v:
        raise err("ERR_INVALID_REQUEST", "field '%s' above maximum" % field)
    return v


def opt_int(body, field, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        return None
    return req_int(body, field, min_v, max_v)


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % field)
    return v


def req_iso(body, field):
    v = body.get(field)
    dt = db.parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "field '%s' must be an ISO-8601 datetime" % field)
    return dt


def opt_str(body, field, min_len=None, max_len=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_str(body, field, min_len, max_len)


_TAX_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")


def req_tax_id_last4(body, field="tax_id_last4"):
    v = body.get(field)
    if not isinstance(v, str) or not _TAX_ID_RE.match(v):
        raise err("ERR_INVALID_REQUEST",
                  "field '%s' must be exactly 4 alphanumeric characters" % field)
    return v
