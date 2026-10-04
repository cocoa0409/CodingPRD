"""Auth header extraction, role checks, and request-body field helpers
(PRD §2.1, §2.8 tiers 1-3)."""

from flask import request

from errors import raise_err

ALL_AUTHENTICATED_ROLES = [
    "Candidate", "ProgramDirector", "StateOfficial",
    "RegistryAdmin", "ExamProctor", "HearingOfficer",
]


def authn(allowed_roles):
    """Validate X-User-ID / X-User-Role and endpoint role authorization.
    Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID") or ""
    role = request.headers.get("X-User-Role") or ""
    if not uid.strip() or not role.strip():
        raise_err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    role = role.strip()
    if role not in allowed_roles:
        raise_err("ERR_FORBIDDEN_ROLE",
                  "Role %s is not authorized for this endpoint" % role)
    return uid.strip(), role


def body():
    """JSON request body as a dict; malformed/absent JSON behaves as {}."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def _fail(field, why):
    raise_err("ERR_INVALID_REQUEST", "Field '%s' %s" % (field, why))


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or not v.strip():
        _fail(field, "is required and must be a non-empty string")
    return v.strip()


def opt_str(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _fail(field, "must be a string")
    return v


def req_enum(b, field, allowed):
    v = b.get(field)
    if not isinstance(v, str) or v not in allowed:
        _fail(field, "must be one of %s" % "|".join(allowed))
    return v


def opt_enum(b, field, allowed, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        _fail(field, "must be one of %s" % "|".join(allowed))
    return v


def req_number(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(field, "is required and must be a number")
    return v


def opt_number(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(field, "must be a number")
    return v


def req_int(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        if isinstance(v, float) and float(v).is_integer():
            return int(v)
        _fail(field, "is required and must be an integer")
    return v


def opt_int(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        if isinstance(v, float) and float(v).is_integer():
            return int(v)
        _fail(field, "must be an integer")
    return v


def req_bool(b, field):
    v = b.get(field)
    if not isinstance(v, bool):
        _fail(field, "is required and must be a boolean")
    return v


def opt_bool(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        _fail(field, "must be a boolean")
    return v


def req_list(b, field):
    v = b.get(field)
    if not isinstance(v, list):
        _fail(field, "is required and must be an array")
    return v


def opt_list(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, list):
        _fail(field, "must be an array")
    return v
