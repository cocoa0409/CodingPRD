"""Request body / query-string validation helpers.

Everything in here raises ERR_INVALID_REQUEST (PRD 2.9 rule 5): required
fields present and non-null, enum values inside their declared set, integers
inside their declared bounds, datetimes valid ISO 8601 UTC instants.
"""
from flask import request

import store
from errors import ApiError

COORD_MIN = -1000000
COORD_MAX = 1000000

_MISSING = object()


def body_json():
    """Parsed JSON object body.  Absent body is treated as an empty object."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def require_present(body, name):
    if not _present(body, name):
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)


def str_field(body, name, required=True, default=None, min_len=None,
              max_len=None, allow_empty=False):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if not allow_empty and value == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must not be empty" % name)
    if min_len is not None and len(value) < min_len:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be at most %d characters" % (name, max_len))
    return value


def int_field(body, name, required=True, default=None, lo=None, hi=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if lo is not None and value < lo:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be greater than or equal to %d" % (name, lo))
    if hi is not None and value > hi:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be less than or equal to %d" % (name, hi))
    return value


def coord_field(body, name, required=True, default=None):
    return int_field(body, name, required=required, default=default,
                     lo=COORD_MIN, hi=COORD_MAX)


def bool_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def enum_field(body, name, choices, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in choices:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be one of %s" % (name, ", ".join(sorted(choices))))
    return value


def dt_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = body[name]
    parsed = store.parse_iso(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be a valid ISO 8601 UTC instant" % name)
    return parsed


# --------------------------------------------------------------------------
# query string helpers
# --------------------------------------------------------------------------

def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def _query_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if lo is not None and value < lo:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be greater than or equal to %d" % (name, lo))
    if hi is not None and value > hi:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be less than or equal to %d" % (name, hi))
    return value


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_enum(name, choices):
    raw = query_str(name)
    if raw is None:
        return None
    if raw not in choices:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be one of %s" % (name, ", ".join(sorted(choices))))
    return raw


def query_bool(name):
    raw = query_str(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be true or false" % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
