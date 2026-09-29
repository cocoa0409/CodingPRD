"""Band 6 — request shape. Every failure here is ERR_INVALID_REQUEST (400)."""
import json
from decimal import Decimal

from flask import request

from errors import ApiError
from money import parse_date
from store import parse_iso_instant

BAD = "ERR_INVALID_REQUEST"


def body():
    """Parsed JSON object. Floats are parsed as Decimal so that the declared
    two-decimal limit on percentages can be enforced exactly."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        raise ApiError(BAD, "Malformed JSON body")
    if not isinstance(parsed, dict):
        raise ApiError(BAD, "Body must be a JSON object")
    return parsed


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _present(data, name):
    if name not in data or data[name] is None:
        raise ApiError(BAD, "Field %s is required" % name)
    return data[name]


def ref(data, name):
    """A body foreign key: returns the raw value, or None when absent/unusable.
    Band 4 only resolves references that are actually present as strings."""
    value = data.get(name)
    if isinstance(value, str):
        return value
    return None


def req_str(data, name):
    value = _present(data, name)
    if not isinstance(value, str):
        raise ApiError(BAD, "Field %s must be a string" % name)
    return value


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str):
        raise ApiError(BAD, "Field %s must be a string" % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    value = _present(data, name)
    if not is_int(value):
        raise ApiError(BAD, "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError(BAD, "Field %s is below its minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError(BAD, "Field %s is above its maximum" % name)
    return value


def req_enum(data, name, allowed):
    value = _present(data, name)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(BAD, "Field %s is not a declared member" % name)
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_pct(data, name, gt=None, ge=None, le=None):
    """A percentage carrying at most two decimal places inside its bound."""
    value = _present(data, name)
    if isinstance(value, bool):
        raise ApiError(BAD, "Field %s must be a number" % name)
    if is_int(value):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        if -value.as_tuple().exponent > 2:
            raise ApiError(BAD, "Field %s carries more than two decimals" % name)
    else:
        raise ApiError(BAD, "Field %s must be a number" % name)
    if gt is not None and not value > Decimal(str(gt)):
        raise ApiError(BAD, "Field %s is out of bounds" % name)
    if ge is not None and not value >= Decimal(str(ge)):
        raise ApiError(BAD, "Field %s is out of bounds" % name)
    if le is not None and not value <= Decimal(str(le)):
        raise ApiError(BAD, "Field %s is out of bounds" % name)
    return value


def req_date(data, name):
    """Returns (raw string, date). Dates are YYYY-MM-DD strings."""
    value = _present(data, name)
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        raise ApiError(BAD, "Field %s must be a YYYY-MM-DD date" % name)
    return value, parsed


def req_instant(data, name):
    """Returns (raw string, datetime). Instants are ISO 8601 UTC timestamps."""
    value = _present(data, name)
    parsed = parse_iso_instant(value) if isinstance(value, str) else None
    if parsed is None:
        raise ApiError(BAD, "Field %s must be an ISO 8601 UTC instant" % name)
    return value, parsed
