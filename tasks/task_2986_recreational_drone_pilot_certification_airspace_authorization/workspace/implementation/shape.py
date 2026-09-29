"""Rung-7 body-shape helpers (PRD 2.11 rung 7) and pagination parsing."""

from flask import request

from clockmod import parse_dt
from errors import ApiError

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def raw_body():
    """The JSON body as a dict.  A non-object body is a malformed request."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise bad("request body is not valid JSON")
    if not isinstance(payload, dict):
        raise bad("request body must be a JSON object")
    return payload


def soft_body():
    """The JSON body when it parses as an object, else an empty dict.

    Used by the ownership rung, which is evaluated before body shape.
    """
    try:
        return raw_body()
    except ApiError:
        return {}


def present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, max_len=None, min_len=1):
    if not present(body, key):
        raise bad("%s is required" % key)
    value = body[key]
    if not isinstance(value, str):
        raise bad("%s must be a string" % key)
    if len(value.strip()) < min_len:
        raise bad("%s must be non-blank" % key)
    if max_len is not None and len(value) > max_len:
        raise bad("%s exceeds %d characters" % (key, max_len))
    return value


def opt_str(body, key, max_len=None):
    if not present(body, key):
        return None
    return req_str(body, key, max_len=max_len)


def req_int(body, key, minimum=None, maximum=None):
    if not present(body, key):
        raise bad("%s is required" % key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        raise bad("%s must be at least %d" % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("%s must be at most %d" % (key, maximum))
    return value


def opt_int(body, key, minimum=None, maximum=None):
    if not present(body, key):
        return None
    return req_int(body, key, minimum=minimum, maximum=maximum)


def req_num(body, key, minimum=None, maximum=None):
    """A decimal-degree style number; integers are accepted as numbers."""
    if not present(body, key):
        raise bad("%s is required" % key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("%s must be a number" % key)
    if minimum is not None and value < minimum:
        raise bad("%s must be at least %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("%s must be at most %s" % (key, maximum))
    return value


def req_object_list(body, key):
    """A required array of JSON objects."""
    if not present(body, key):
        raise bad("%s is required" % key)
    value = body[key]
    if not isinstance(value, list):
        raise bad("%s must be an array" % key)
    for item in value:
        if not isinstance(item, dict):
            raise bad("%s must contain objects" % key)
    return value


def req_bool(body, key):
    if not present(body, key):
        raise bad("%s is required" % key)
    value = body[key]
    if not isinstance(value, bool):
        raise bad("%s must be a boolean" % key)
    return value


def opt_bool(body, key, default=None):
    if not present(body, key):
        return default
    return req_bool(body, key)


def req_enum(body, key, members):
    value = req_str(body, key)
    if value not in members:
        raise bad("%s must be one of %s" % (key, ", ".join(sorted(members))))
    return value


def opt_enum(body, key, members):
    if not present(body, key):
        return None
    return req_enum(body, key, members)


def req_dt(body, key):
    if not present(body, key):
        raise bad("%s is required" % key)
    parsed = parse_dt(body[key])
    if parsed is None:
        raise bad("%s must be an ISO-8601 instant" % key)
    return parsed


def opt_dt(body, key):
    if not present(body, key):
        return None
    return req_dt(body, key)


def req_id(body, key):
    return req_str(body, key)


def opt_id(body, key):
    return opt_str(body, key)


def req_id_list(body, key, allow_missing=True):
    """A list of resource ids; missing is treated as the empty list."""
    if not present(body, key):
        if allow_missing:
            return []
        raise bad("%s is required" % key)
    value = body[key]
    if not isinstance(value, list):
        raise bad("%s must be an array" % key)
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise bad("%s must contain resource ids" % key)
        out.append(item)
    return out


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            raise bad("limit must be an integer")
        if limit_value < PAGE_LIMIT_MIN or limit_value > PAGE_LIMIT_MAX:
            raise bad("limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if offset is None or offset == "":
        offset_value = 0
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            raise bad("offset must be an integer")
        if offset_value < 0:
            raise bad("offset must not be negative")
    return limit_value, offset_value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def query_dt(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    parsed = parse_dt(value)
    if parsed is None:
        raise bad("%s must be an ISO-8601 instant" % key)
    return parsed


def query_str(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    return value


def query_bool(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("%s must be a boolean" % key)
