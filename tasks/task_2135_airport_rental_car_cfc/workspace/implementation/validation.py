"""Request admission helpers — PRD sections 2.1, 2.3, 2.6."""

import datetime
import functools

from flask import g, request

from errors import ApiError

ROLES = ("FacilityAdmin", "ConcessionaireOperator", "AuditOfficer", "FinanceOfficer")
ALL_ROLES = list(ROLES)

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def _bad(msg):
    return ApiError("ERR_INVALID_REQUEST", msg)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def authorize(roles):
    if g.role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def endpoint(roles):
    """Ladder steps 1 and 2 for every handler."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# --------------------------------------------------------------------------
# Body parsing (ladder step 3)
# --------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        raise _bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise _bad("Request body must be a JSON object.")
    return payload


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        raise _bad("Missing required field '%s'." % name)
    value = data[name]
    if not _is_int(value):
        raise _bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise _bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise _bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(data, name, default, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum, maximum)


def req_str(data, name, min_len=1, max_len=None, upper=False):
    if name not in data or data[name] is None:
        raise _bad("Missing required field '%s'." % name)
    value = data[name]
    if not isinstance(value, str):
        raise _bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise _bad("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        raise _bad("Field '%s' is too long." % name)
    if upper and value != value.upper():
        raise _bad("Field '%s' must be uppercase." % name)
    return value


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str):
        raise _bad("Field '%s' must be a string." % name)
    return value


def req_enum(data, name, members):
    value = req_str(data, name)
    if value not in members:
        raise _bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def req_bool(data, name):
    if name not in data or data[name] is None:
        raise _bad("Missing required field '%s'." % name)
    if not isinstance(data[name], bool):
        raise _bad("Field '%s' must be a boolean." % name)
    return data[name]


def opt_bool(data, name, default):
    if name not in data or data[name] is None:
        return default
    return req_bool(data, name)


def parse_date(value, name):
    if not isinstance(value, str) or len(value) != 10:
        raise _bad("Field '%s' must be a YYYY-MM-DD date." % name)
    try:
        return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10])) \
            if value[4] == "-" and value[7] == "-" else None
    except (ValueError, TypeError):
        raise _bad("Field '%s' must be a YYYY-MM-DD date." % name)


def req_date(data, name):
    if name not in data or data[name] is None:
        raise _bad("Missing required field '%s'." % name)
    parsed = parse_date(data[name], name)
    if parsed is None:
        raise _bad("Field '%s' must be a YYYY-MM-DD date." % name)
    return data[name]


def to_date(value):
    return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


# --------------------------------------------------------------------------
# Query string handling
# --------------------------------------------------------------------------

def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise _bad("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise _bad("limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _bad("offset must be an integer.")
        if offset < 0:
            raise _bad("offset may not be negative.")
    return limit, offset


def q_str(name):
    return request.args.get(name)


def q_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        raise _bad("Unrecognised value for filter '%s'." % name)
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _bad("Filter '%s' must be an integer." % name)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(r) for r in window], limit, offset, total
