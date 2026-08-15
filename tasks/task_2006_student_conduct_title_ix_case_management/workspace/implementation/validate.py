"""Request-body helpers.

Two families:
- strict `req_*`/`opt_*` validators raise ERR_INVALID_REQUEST (tier 11, schema).
  Endpoint logic calls them LAST, after higher-priority business checks.
- loose probes (`as_*`) return None on type mismatch so business-rule checks at
  earlier tiers can evaluate only when the needed fields are present and typed;
  malformed fields fall through to the strict pass at the end.
"""
from datetime import datetime

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Loose probes (never raise)
# ---------------------------------------------------------------------------

def as_str(body, field):
    v = body.get(field)
    return v if isinstance(v, str) else None


def as_bool(body, field):
    v = body.get(field)
    return v if isinstance(v, bool) else None


def as_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def as_num(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def as_list(body, field):
    v = body.get(field)
    return v if isinstance(v, list) else None


def is_valid_iso(s) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    try:
        if t.endswith("Z"):
            datetime.fromisoformat(t[:-1] + "+00:00")
        else:
            datetime.fromisoformat(t)
        return True
    except (ValueError, TypeError):
        return False


def as_datetime(body, field):
    v = body.get(field)
    return v if is_valid_iso(v) else None


def as_enum(body, field, allowed):
    v = body.get(field)
    if isinstance(v, str) and v in allowed:
        return v
    return None


def as_enum_list(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, list) or len(v) == 0:
        return None
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            return None
    return list(v)


# ---------------------------------------------------------------------------
# Strict validators (raise ERR_INVALID_REQUEST) — schema tier, evaluated last
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum,
                   positive=positive, non_negative=non_negative)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_datetime(body, field):
    v = body.get(field)
    if not is_valid_iso(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    return v.strip()


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def req_enum_list(body, field, allowed):
    """Non-empty array whose members all belong to `allowed`."""
    v = body.get(field)
    if not isinstance(v, list) or len(v) == 0:
        raise_error(ERR_INVALID_REQUEST, f"missing or empty array field: {field}")
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"field {field} contains invalid value: {item!r}")
    return list(v)


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    return v


# ---------------------------------------------------------------------------
# Existence (tier 3)
# ---------------------------------------------------------------------------

def require_path(collection, rid):
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_profile_fk(body, field):
    """Body FK to PartyProfile: resolvable strings must exist (404); missing or
    mistyped values are left for the schema pass (tier 11)."""
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        return None
    obj = db["party_profiles"].get(v)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve to a PartyProfile: {v}")
    return obj
