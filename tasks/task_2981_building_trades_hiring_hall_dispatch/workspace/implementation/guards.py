"""§2.1 header authentication / RBAC and §2.7 priority-3 request-shape checks."""

from flask import request

from core import ROLES, parse_iso
from envelope import ApiError

_MISSING = object()


# --------------------------------------------------------------------------
# priority 1 + 2
# --------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-empty.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognized role.")
    return user_id, role


def require(*allowed_roles):
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
    return user_id, role


# --------------------------------------------------------------------------
# priority 3 — request shape
# --------------------------------------------------------------------------
def body():
    raw = request.get_data()
    if not raw or not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(data, field):
    return field in data and data[field] is not None


def s_str(data, field, required=True, min_len=1, max_len=None, default=None):
    if field not in data or data[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def s_int(data, field, required=True, minimum=None, maximum=None, default=None):
    if field not in data or data[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def s_bool(data, field, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def s_enum(data, field, allowed, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def s_dt(data, field, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 UTC instant string")
    parsed = parse_iso(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant string")
    return parsed


def s_id_array(data, field, default=None):
    if field not in data or data[field] is None:
        return list(default) if default is not None else []
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for item in value:
        if not isinstance(item, str) or not item:
            _bad(field, "must be an array of non-empty id strings")
    return list(value)


def s_reciprocity_credits(data, field="reciprocity_credits"):
    if field not in data or data[field] is None:
        return []
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    out = []
    for item in value:
        if not isinstance(item, dict):
            _bad(field, "must be an array of objects")
        local_id = item.get("sister_local_id")
        if not isinstance(local_id, str) or not local_id:
            _bad(field, "entries require a string sister_local_id")
        raw_hours = item.get("raw_hours")
        if isinstance(raw_hours, bool) or not isinstance(raw_hours, int):
            _bad(field, "entries require an integer raw_hours")
        if raw_hours < 0:
            _bad(field, "entries require raw_hours >= 0")
        out.append({"sister_local_id": local_id, "raw_hours": raw_hours})
    return out


# --------------------------------------------------------------------------
# query-string helpers
# --------------------------------------------------------------------------
def q_enum(field, allowed):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def q_str(field):
    value = request.args.get(field)
    if value is None:
        return None
    return value


def q_bool(field):
    value = request.args.get(field)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad(field, "must be a boolean")


def _q_int(field, default, minimum, maximum):
    raw = request.args.get(field)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        _bad(field, "must be an integer")
    value = int(text)
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def pagination():
    """§2.3 — limit default 10 (1..100), offset default 0 (>= 0)."""
    limit = _q_int("limit", 10, 1, 100)
    offset = _q_int("offset", 0, 0, None)
    return limit, offset


def check_pagination_shape():
    """Validate limit/offset whenever supplied, on every endpoint (§2.7 item 3)."""
    pagination()


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
