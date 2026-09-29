"""Request-body schema conformance (ladder rung 4 -- ERR_VALIDATION, 400).

Every helper here raises ERR_VALIDATION and nothing else: required fields being
present, enum values being declared members, dates being YYYY-MM-DD, instants
being ISO-8601 UTC with a trailing Z, money having at most two fraction digits
and being strictly positive where the field demands it, and integers falling
inside their declared ranges (PRD 2.7 rung 4).
"""

from flask import request

from errors import bad_request
from util import fraction_digits, parse_date, parse_instant, to_decimal

MISSING = object()


def body_json():
    """The request body as an object.  A non-object body is a schema violation."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def _get(body, name, required):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return MISSING
    return body[name]


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------
def _check_str(name, value, min_len, max_len, must_contain):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request(
            "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request(
            "Field '%s' must be at most %d characters." % (name, max_len))
    if must_contain is not None and must_contain not in value:
        raise bad_request("Field '%s' must contain '%s'." % (name, must_contain))
    return value


def req_str(body, name, min_len=None, max_len=None, must_contain=None):
    return _check_str(name, _get(body, name, True), min_len, max_len, must_contain)


def opt_str(body, name, default=None, min_len=None, max_len=None):
    value = _get(body, name, False)
    if value is MISSING:
        return default
    return _check_str(name, value, min_len, max_len, None)


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------
def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be at most %d." % (name, maximum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    return _check_int(name, _get(body, name, True), minimum, maximum)


def opt_int(body, name, default=0, minimum=None, maximum=None):
    value = _get(body, name, False)
    if value is MISSING:
        return default
    return _check_int(name, value, minimum, maximum)


# --------------------------------------------------------------------------
# money
# --------------------------------------------------------------------------
def _check_money(name, value, positive):
    amount = to_decimal(value)
    if amount is None or isinstance(value, bool) or isinstance(value, str):
        raise bad_request("Field '%s' must be a decimal amount." % name)
    digits = fraction_digits(value)
    if digits is None or digits > 2:
        raise bad_request(
            "Field '%s' must carry at most two fraction digits." % name)
    if positive and amount <= 0:
        raise bad_request("Field '%s' must be strictly positive." % name)
    if not positive and amount < 0:
        raise bad_request("Field '%s' must not be negative." % name)
    return amount


def req_money(body, name, positive=True):
    return _check_money(name, _get(body, name, True), positive)


def opt_money(body, name, default=None, positive=True):
    value = _get(body, name, False)
    if value is MISSING:
        return default
    return _check_money(name, value, positive)


# --------------------------------------------------------------------------
# enums, dates, instants, references
# --------------------------------------------------------------------------
def req_enum(body, name, allowed):
    value = _get(body, name, True)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    value = _get(body, name, False)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_date(body, name):
    value = _get(body, name, True)
    parsed = parse_date(value)
    if parsed is None:
        raise bad_request("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return parsed


def req_instant(body, name):
    value = _get(body, name, True)
    parsed = parse_instant(value)
    if parsed is None:
        raise bad_request(
            "Field '%s' must be an ISO-8601 UTC instant ending in Z." % name)
    return parsed


def req_ref(body, name):
    """A foreign key: a non-empty string here, resolved at ladder rung 6."""
    value = _get(body, name, True)
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be a resource identifier." % name)
    return value


def opt_ref(body, name, default=None):
    value = _get(body, name, False)
    if value is MISSING:
        return default
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be a resource identifier." % name)
    return value


def req_enum_list(body, name, allowed):
    value = _get(body, name, True)
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad_request(
                "Field '%s' entries must be one of %s." % (name, ", ".join(allowed)))
    return list(value)


def req_str_list(body, name):
    """An array of open-vocabulary codes -- the PRD names examples, not members."""
    value = _get(body, name, True)
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or not item:
            raise bad_request("Field '%s' entries must be non-empty strings." % name)
    return list(value)


def strictly_before(left, right, left_name, right_name):
    if not left < right:
        raise bad_request(
            "'%s' must be strictly earlier than '%s'." % (left_name, right_name))


def query_enum(args, name, allowed):
    """A filter whose value must be a declared enum member."""
    value = args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad_request(
            "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_int(args, name):
    value = args.get(name)
    if value is None:
        return None
    text = str(value).strip()
    try:
        if text != str(int(text)):
            raise ValueError
        return int(text)
    except ValueError:
        raise bad_request("Query parameter '%s' must be an integer." % name)


def query_str(args, name):
    value = args.get(name)
    if value is None:
        return None
    return value
