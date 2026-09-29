"""Request shape validation -- validation priority 3, ERR_INVALID_REQUEST 400."""
from flask import request

from errors import ApiError, bad_request
from util import D, parse_date, parse_instant

MISSING = object()


def json_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        raise bad_request("Request body must be valid JSON")
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object")
    return parsed


def _fetch(body, name, required, default):
    if name not in body:
        if required:
            raise bad_request("Missing required field '%s'" % name)
        return MISSING if default is MISSING else default
    return body[name]


def field_string(body, name, required=False, default=None, min_len=1,
                 max_len=None, nullable=False, pattern=None):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' is too short" % name)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' is too long" % name)
    if pattern is not None and not pattern.match(value):
        raise bad_request("Field '%s' is malformed" % name)
    return value


def field_int(body, name, required=False, default=None, minimum=None,
              maximum=None, nullable=False):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its minimum" % name)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its maximum" % name)
    return value


def field_number(body, name, required=False, default=None, minimum=None,
                 maximum=None, exclusive_min=None, nullable=False,
                 decimals=2):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number" % name)
    dec = D(value)
    if decimals is not None and dec.as_tuple().exponent < -decimals:
        raise bad_request(
            "Field '%s' carries more than %d decimal places" % (name, decimals)
        )
    if exclusive_min is not None and dec <= D(exclusive_min):
        raise bad_request("Field '%s' must be greater than %s"
                          % (name, exclusive_min))
    if minimum is not None and dec < D(minimum):
        raise bad_request("Field '%s' is below its minimum" % name)
    if maximum is not None and dec > D(maximum):
        raise bad_request("Field '%s' is above its maximum" % name)
    return dec


def field_bool(body, name, required=False, default=None, nullable=False):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean" % name)
    return value


def field_enum(body, name, allowed, required=False, default=None,
               nullable=False):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' is not a declared enum member" % name)
    return value


def field_date(body, name, required=False, default=None, nullable=False):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    parsed = parse_date(value)
    if parsed is None:
        raise bad_request("Field '%s' must be a YYYY-MM-DD date" % name)
    return parsed


def field_instant(body, name, required=False, default=None, nullable=False):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must not be null" % name)
    parsed = parse_instant(value)
    if parsed is None:
        raise bad_request(
            "Field '%s' must be an ISO 8601 UTC instant" % name
        )
    return parsed


def field_array(body, name, required=False, default=None, min_items=None,
                max_items=None):
    value = _fetch(body, name, required, default)
    if value is MISSING or (value is default and name not in body):
        return value
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array" % name)
    if min_items is not None and len(value) < min_items:
        raise bad_request("Field '%s' has too few entries" % name)
    if max_items is not None and len(value) > max_items:
        raise bad_request("Field '%s' has too many entries" % name)
    return value


# --- query string ----------------------------------------------------------
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw, 10)
    except (TypeError, ValueError):
        raise bad_request("Query parameter '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("Query parameter '%s' is out of range" % name)
    if maximum is not None and value > maximum:
        raise bad_request("Query parameter '%s' is out of range" % name)
    return value


def pagination():
    """limit default 10 (1..100), offset default 0 (>= 0)."""
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_enum(name, allowed):
    raw = query_string(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise bad_request(
            "Query parameter '%s' is not a declared enum member" % name
        )
    return raw


def query_bool(name):
    raw = query_string(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean" % name)


def query_date(name, required=False):
    raw = query_string(name)
    if raw is None:
        if required:
            raise bad_request("Query parameter '%s' is required" % name)
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise bad_request(
            "Query parameter '%s' must be a YYYY-MM-DD date" % name
        )
    return parsed


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
