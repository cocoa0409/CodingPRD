"""Request-shape validation (PRD 2.10 step 3 -> ERR_INVALID_REQUEST, 400)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_instant

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Parsed JSON object body; an absent body is treated as {}."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        bad("Request body must be valid JSON.")
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, min_len=1, max_len=None):
    if not present(body, name):
        bad("%s is required." % name)
    return _check_string(body[name], name, min_len, max_len)


def opt_string(body, name, min_len=1, max_len=None, default=None):
    if not present(body, name):
        return default
    return _check_string(body[name], name, min_len, max_len)


def _check_string(value, name, min_len, max_len):
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s is longer than %d characters." % (name, max_len))
    return value


def req_station(body, name):
    value = req_string(body, name, 3, 3)
    if not (value.isalpha() and value.isupper()):
        bad("%s must be exactly three uppercase letters." % name)
    return value


def req_country(body, name):
    value = req_string(body, name, 2, 2)
    if not (value.isalpha() and value.isupper()):
        bad("%s must be exactly two uppercase letters." % name)
    return value


def req_enum(body, name, allowed):
    if not present(body, name):
        bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def _check_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %d." % (name, maximum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not present(body, name):
        bad("%s is required." % name)
    return _check_int(body[name], name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not present(body, name):
        return default
    return _check_int(body[name], name, minimum, maximum)


def _to_decimal(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number." % name)


def _check_decimal(value, name, lo, hi, decimals, lo_exclusive):
    number = _to_decimal(value, name)
    # PRD 2.6: a percentage outside [0, 1] inclusive is ERR_INVALID_REQUEST.
    if lo is not None:
        if lo_exclusive and number <= lo:
            bad("%s must be strictly greater than %s." % (name, lo))
        if not lo_exclusive and number < lo:
            bad("%s must be >= %s." % (name, lo))
    if hi is not None and number > hi:
        bad("%s must be <= %s." % (name, hi))
    if decimals is not None:
        exponent = number.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -decimals:
            bad("%s accepts at most %d decimal places." % (name, decimals))
    return number


def req_decimal(body, name, lo, hi, decimals, lo_exclusive=False):
    if not present(body, name):
        bad("%s is required." % name)
    return _check_decimal(body[name], name, lo, hi, decimals, lo_exclusive)


def opt_decimal(body, name, lo, hi, decimals, default, lo_exclusive=False):
    if not present(body, name):
        return default
    return _check_decimal(body[name], name, lo, hi, decimals, lo_exclusive)


def _check_bool(value, name):
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    return _check_bool(body[name], name)


def req_instant(body, name):
    if not present(body, name):
        bad("%s is required." % name)
    return _check_instant(body[name], name)


def opt_instant(body, name, default=None):
    if not present(body, name):
        return default
    return _check_instant(body[name], name)


def _check_instant(value, name):
    try:
        return parse_instant(value)
    except (ValueError, TypeError):
        bad("%s must be an ISO 8601 UTC instant." % name)


def opt_str_array(body, name, default=None, min_entries=None, max_entries=None):
    if not present(body, name):
        return list(default) if default is not None else None
    return _check_str_array(body[name], name, min_entries, max_entries)


def req_str_array(body, name, min_entries=None, max_entries=None):
    if not present(body, name):
        bad("%s is required." % name)
    return _check_str_array(body[name], name, min_entries, max_entries)


def _check_str_array(value, name, min_entries, max_entries):
    if not isinstance(value, list):
        bad("%s must be an array of strings." % name)
    for entry in value:
        if not isinstance(entry, str):
            bad("%s must be an array of strings." % name)
    if min_entries is not None and len(value) < min_entries:
        bad("%s requires at least %d entries." % (name, min_entries))
    if max_entries is not None and len(value) > max_entries:
        bad("%s accepts at most %d entries." % (name, max_entries))
    return list(value)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
