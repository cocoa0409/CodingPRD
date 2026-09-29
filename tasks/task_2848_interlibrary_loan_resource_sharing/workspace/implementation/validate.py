"""Payload / query validation helpers (rung 35 of the ladder)."""
from flask import request

from db import parse_instant
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad("Request body is not valid JSON.")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _is_int(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return float(value).is_integer()
    return False


def as_int(value, name, minimum=None, maximum=None):
    if not _is_int(value):
        bad("Field '%s' must be an integer." % name)
    number = int(value)
    if minimum is not None and number < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and number > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    return number


def req_int(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    return as_int(data[name], name, minimum, maximum)


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return as_int(data[name], name, minimum, maximum)


def req_str(data, name, min_len=1, max_len=None):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, default=None, min_len=None, max_len=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_bool(data, name):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def req_instant(data, name):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    try:
        return parse_instant(data[name])
    except (ValueError, TypeError):
        bad("Field '%s' must be an ISO 8601 instant." % name)


def opt_instant(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    try:
        return parse_instant(data[name])
    except (ValueError, TypeError):
        bad("Field '%s' must be an ISO 8601 instant." % name)


def req_id(data, name):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an identifier string." % name)
    return value


def raw_id(data, name):
    """The value of a foreign-key field for the rung-32 existence sweep."""
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value


# --- query string --------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (ValueError, TypeError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (ValueError, TypeError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        bad("Query parameter '%s' must be an integer." % name)


def page(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
