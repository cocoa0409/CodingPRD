"""Request-shape validation - PRD ladder level 6.

Everything in this module raises ERR_INVALID_REQUEST and nothing else: "required
fields present and non-null, types correct, enum values recognised, numbers
inside their declared ranges, strings matching their declared patterns, and
interval field pairs not inverted".
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_instant

_MISSING = object()


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; an absent body reads as an empty object."""
    try:
        payload = request.get_json(silent=True)
    except Exception:
        raise _bad("Malformed JSON body.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise _bad("The request body must be a JSON object.")
    return payload


def _present(data, key):
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        return None
    return value


def req_str(data, key, pattern=None):
    value = _present(data, key)
    if value is None:
        raise _bad("%s is required." % key)
    if not isinstance(value, str):
        raise _bad("%s must be a string." % key)
    if not value.strip():
        raise _bad("%s must not be blank." % key)
    if pattern is not None and re.match(pattern, value) is None:
        raise _bad("%s does not match its required format." % key)
    return value


def opt_str(data, key, default=None):
    value = _present(data, key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise _bad("%s must be a string." % key)
    if not value.strip():
        raise _bad("%s must not be blank." % key)
    return value


def req_id(data, key):
    """A body foreign key: it must be a non-blank string before it is resolved."""
    return req_str(data, key)


def _as_int(key, value):
    if isinstance(value, bool):
        raise _bad("%s must be an integer." % key)
    if isinstance(value, int):
        return value
    raise _bad("%s must be an integer." % key)


def req_int(data, key, minimum=None, maximum=None):
    value = _present(data, key)
    if value is None:
        raise _bad("%s is required." % key)
    parsed = _as_int(key, value)
    _range_check(key, Decimal(parsed), minimum, maximum, False, False)
    return parsed


def opt_int(data, key, default=None, minimum=None, maximum=None):
    value = _present(data, key)
    if value is None:
        return default
    parsed = _as_int(key, value)
    _range_check(key, Decimal(parsed), minimum, maximum, False, False)
    return parsed


def _as_decimal(key, value):
    if isinstance(value, bool):
        raise _bad("%s must be a number." % key)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        try:
            return Decimal(repr(value))
        except InvalidOperation:
            raise _bad("%s must be a number." % key)
    raise _bad("%s must be a number." % key)


def _range_check(key, parsed, minimum, maximum, exclusive_min, exclusive_max):
    if minimum is not None:
        if exclusive_min and parsed <= minimum:
            raise _bad("%s must be greater than %s." % (key, minimum))
        if not exclusive_min and parsed < minimum:
            raise _bad("%s must be at least %s." % (key, minimum))
    if maximum is not None:
        if exclusive_max and parsed >= maximum:
            raise _bad("%s must be less than %s." % (key, maximum))
        if not exclusive_max and parsed > maximum:
            raise _bad("%s must not exceed %s." % (key, maximum))


def req_num(data, key, minimum=None, maximum=None, exclusive_min=False, exclusive_max=False):
    value = _present(data, key)
    if value is None:
        raise _bad("%s is required." % key)
    parsed = _as_decimal(key, value)
    _range_check(key, parsed, minimum, maximum, exclusive_min, exclusive_max)
    return parsed


def opt_num(data, key, default=None, minimum=None, maximum=None,
            exclusive_min=False, exclusive_max=False):
    value = _present(data, key)
    if value is None:
        return default
    parsed = _as_decimal(key, value)
    _range_check(key, parsed, minimum, maximum, exclusive_min, exclusive_max)
    return parsed


def req_enum(data, key, allowed):
    value = _present(data, key)
    if value is None:
        raise _bad("%s is required." % key)
    if not isinstance(value, str) or value not in allowed:
        raise _bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    value = _present(data, key)
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise _bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def req_instant(data, key):
    value = _present(data, key)
    if value is None:
        raise _bad("%s is required." % key)
    return parse_instant(value)


def opt_instant(data, key, default=None):
    value = _present(data, key)
    if value is None:
        return default
    return parse_instant(value)


def not_after_clock(key, moment, current):
    """PRD 2.4: a sampled_at or taken_at instant may not be after the clock."""
    if moment > current:
        raise _bad("%s must not be after the logical clock." % key)


def strictly_after(later_key, later, earlier_key, earlier):
    """PRD 2.10 level 6: interval field pairs must not be inverted."""
    if later <= earlier:
        raise _bad("%s must be strictly after %s." % (later_key, earlier_key))
