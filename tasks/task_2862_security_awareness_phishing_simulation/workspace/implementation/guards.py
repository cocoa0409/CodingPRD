"""Authentication, authorization and request well-formedness (PRD 2.1, 2.3, 2.8)."""
from flask import request

from errors import fail
from store import parse_date, parse_instant

ROLES = (
    "ProgramAdmin",
    "CampaignAuthor",
    "CampaignApprover",
    "Manager",
    "Learner",
    "SecurityAnalyst",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty")
    if not role or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role")
    return Actor(user_id.strip(), role)


def authorize(*allowed):
    actor = authenticate()
    if actor.role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % actor.role)
    return actor


# ----------------------------------------------------------------- body access
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _missing(key):
    fail("ERR_INVALID_REQUEST", "field '%s' is required" % key)


def req_str(data, key, allow_empty=False):
    if key not in data or data[key] is None:
        _missing(key)
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a string" % key)
    if not allow_empty and not value.strip():
        fail("ERR_INVALID_REQUEST", "field '%s' must be a non-empty string" % key)
    return value


def opt_str(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    if not isinstance(data[key], str):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a string" % key)
    return data[key]


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "field '%s' is not a recognised value" % key)
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "field '%s' is not a recognised value" % key)
    return value


def _as_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an integer" % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        _missing(key)
    value = _as_int(key, data[key])
    _range(key, value, minimum, maximum)
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        return default
    value = _as_int(key, data[key])
    _range(key, value, minimum, maximum)
    return value


def _range(key, value, minimum, maximum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "field '%s' is below its minimum" % key)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "field '%s' is above its maximum" % key)


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    if not isinstance(data[key], bool):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % key)
    return data[key]


def req_instant(data, key):
    if key not in data or data[key] is None:
        _missing(key)
    parsed = parse_instant(data[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "field '%s' must be an ISO-8601 instant" % key)
    return parsed


def req_date(data, key):
    if key not in data or data[key] is None:
        _missing(key)
    parsed = parse_date(data[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "field '%s' must be a YYYY-MM-DD date" % key)
    return parsed


def opt_id(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    if not isinstance(data[key], str) or not data[key].strip():
        fail("ERR_INVALID_REQUEST", "field '%s' must be a non-empty string" % key)
    return data[key]


def opt_enum_array(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return list(default or [])
    value = data[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an array" % key)
    seen = set()
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            fail("ERR_INVALID_REQUEST", "field '%s' contains an unrecognised value" % key)
        if entry in seen:
            fail("ERR_INVALID_REQUEST", "field '%s' contains duplicate entries" % key)
        seen.add(entry)
    return list(value)


def opt_int_array(data, key, default=None):
    if key not in data or data[key] is None:
        return list(default or [])
    value = data[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an array" % key)
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int):
            fail("ERR_INVALID_REQUEST", "field '%s' must contain integers" % key)
    return list(value)


# ---------------------------------------------------------------- query params
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def query_enum(key, allowed):
    value = request.args.get(key)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "query parameter '%s' is not a recognised value" % key)
    return value


def query_str(key):
    value = request.args.get(key)
    if value is None:
        return None
    return value


def query_int(key, minimum=None, maximum=None):
    value = request.args.get(key)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "query parameter '%s' must be an integer" % key)
    _range(key, parsed, minimum, maximum)
    return parsed


def query_instant(key, required=False):
    value = request.args.get(key)
    if value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "query parameter '%s' is required" % key)
        return None
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "query parameter '%s' must be an ISO-8601 instant" % key)
    return parsed
