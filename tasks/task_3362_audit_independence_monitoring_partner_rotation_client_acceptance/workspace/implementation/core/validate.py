"""Request-shape validation (validation cascade priority 1).

Body fields are validated against the endpoint's declared schema: required
fields must be present, enum members must be valid, numeric ranges respected
and undeclared fields rejected.
"""

from decimal import Decimal, InvalidOperation

from .errors import ERR_INVALID_REQUEST, ApiError
from .utils import parse_datetime

_MISSING = object()


def fail(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def body_object(payload):
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("The request body must be a JSON object.")
    return payload


def reject_unknown(body, declared):
    unknown = [key for key in body.keys() if key not in declared]
    if unknown:
        fail("Unknown field(s) supplied: " + ", ".join(sorted(unknown)) + ".")


def _present(body, name):
    if name not in body:
        return _MISSING
    value = body[name]
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def string(body, name, required=False, default=None, nullable=False):
    value = _present(body, name)
    if value is _MISSING or value is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    if not isinstance(value, str):
        fail("Field '%s' must be a string." % name)
    return value


def enum(body, name, allowed, required=False, default=None, nullable=False):
    value = _present(body, name)
    if value is _MISSING or value is None:
        if required:
            fail("Field '%s' is required." % name)
        if nullable:
            return None
        return default
    if not isinstance(value, str) or value not in allowed:
        fail("Field '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return value


def boolean(body, name, default=False):
    value = _present(body, name)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        fail("Field '%s' must be a boolean." % name)
    return value


def number(body, name, required=False, default=None, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING or value is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        fail("Field '%s' must be a number." % name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("Field '%s' must be a number." % name)
    if parsed != parsed or parsed.is_infinite():
        fail("Field '%s' must be a finite number." % name)
    if minimum is not None and parsed < Decimal(str(minimum)):
        fail("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and parsed > Decimal(str(maximum)):
        fail("Field '%s' must be <= %s." % (name, maximum))
    return parsed


def integer(body, name, required=False, default=None, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING or value is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    if isinstance(value, bool):
        fail("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        parsed = value
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            fail("Field '%s' must be an integer." % name)
        if decimal_value != decimal_value.to_integral_value():
            fail("Field '%s' must be an integer." % name)
        parsed = int(decimal_value)
    if minimum is not None and parsed < minimum:
        fail("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and parsed > maximum:
        fail("Field '%s' must be <= %s." % (name, maximum))
    return parsed


def datetime_field(body, name, required=False, default=None, nullable=False):
    value = _present(body, name)
    if value is _MISSING or value is None:
        if required:
            fail("Field '%s' is required." % name)
        if nullable:
            return None
        return default
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        fail("Field '%s' must be an ISO-8601 UTC instant." % name)
    return parsed


def raw_datetime(body, name, required=False, default=None, nullable=False):
    """Parse a datetime but keep the caller's original text for echoing."""
    value = _present(body, name)
    if value is _MISSING or value is None:
        if required:
            fail("Field '%s' is required." % name)
        if nullable:
            return None, None
        return default, None
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        fail("Field '%s' must be an ISO-8601 UTC instant." % name)
    return parsed, value
