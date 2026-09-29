"""Request-shape validation — ladder priority 3, ERR_INVALID_REQUEST (422)."""
import json
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import dec, decimals_of, parse_date, parse_instant

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal, parse_int=int)
    except (ValueError, InvalidOperation):
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def present(data, name):
    return name in data and data[name] is not None


def raw_value(data, name):
    return data.get(name, MISSING)


def _fetch(data, name, required, default):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default, False
    return value, True


def string(data, name, required=True, default=None, min_len=None, max_len=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters." % (name, max_len))
    return value


def enum(data, name, allowed, required=True, default=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def boolean(data, name, required=False, default=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def integer(data, name, required=True, default=None, minimum=None, maximum=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be an integer." % name)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            bad("Field '%s' must be an integer." % name)
        value = int(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below the permitted minimum." % name)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above the permitted maximum." % name)
    return value


def number(data, name, required=True, default=None, minimum=None, maximum=None,
           min_exclusive=False, max_exclusive=False, max_places=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be a number." % name)
    if max_places is not None and decimals_of(value) > max_places:
        bad("Field '%s' carries more than %d decimal places." % (name, max_places))
    value = dec(value)
    if minimum is not None:
        limit = dec(minimum)
        if value < limit or (min_exclusive and value == limit):
            bad("Field '%s' is below the permitted minimum." % name)
    if maximum is not None:
        limit = dec(maximum)
        if value > limit or (max_exclusive and value == limit):
            bad("Field '%s' is above the permitted maximum." % name)
    return value


def date_field(data, name, required=True, default=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD string." % name)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' is not a valid calendar date." % name)
    return parsed


def instant_field(data, name, required=True, default=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 instant." % name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' is not a valid ISO 8601 instant." % name)
    return parsed


def enum_array(data, name, allowed, required=True, default=None,
               non_empty=True, unique=True):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if non_empty and not value:
        bad("Field '%s' must not be empty." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("Field '%s' contains an unrecognised value." % name)
    if unique and len(set(value)) != len(value):
        bad("Field '%s' must not repeat a value." % name)
    return list(value)


def int_array(data, name, required=True, default=None, non_empty=True,
              minimum=None, maximum=None):
    value, found = _fetch(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if non_empty and not value:
        bad("Field '%s' must not be empty." % name)
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, Decimal)):
            bad("Field '%s' must contain integers." % name)
        if isinstance(item, Decimal):
            if item != item.to_integral_value():
                bad("Field '%s' must contain integers." % name)
            item = int(item)
        if minimum is not None and item < minimum:
            bad("Field '%s' contains a value below the permitted minimum." % name)
        if maximum is not None and item > maximum:
            bad("Field '%s' contains a value above the permitted maximum." % name)
        result.append(item)
    return result


def bool_param(name, default=False):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)
