"""Request shape validation (PRD 2.10 step 7). Every failure is ERR_INVALID_REQUEST."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ApiError
from store import try_parse_dt

TWO = Decimal("0.01")


def bad(field, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def body():
    """The JSON request body as a dict; a missing body is an empty object."""
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("body", "must be a JSON object")
    return payload


def present(data, field):
    return field in data and data[field] is not None


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------


def req_str(data, field, min_len=1, max_len=None, blank_ok=True):
    if not present(data, field):
        bad(field, "is required")
    return _as_str(data[field], field, min_len, max_len, blank_ok)


def opt_str(data, field, min_len=1, max_len=None, default=None, blank_ok=True):
    if not present(data, field):
        return default
    return _as_str(data[field], field, min_len, max_len, blank_ok)


def _as_str(value, field, min_len, max_len, blank_ok):
    if not isinstance(value, str):
        bad(field, "must be a string")
    if len(value) < min_len:
        bad(field, "is too short")
    if max_len is not None and len(value) > max_len:
        bad(field, "is too long")
    if not blank_ok and value.strip() == "":
        bad(field, "must not be blank")
    return value


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad(field, "is required")
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool):
        bad(field, "must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if value != int(value):
            bad(field, "must be a whole number")
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        try:
            dec = Decimal(text)
        except (InvalidOperation, ValueError):
            bad(field, "must be an integer")
        if dec != dec.to_integral_value():
            bad(field, "must be a whole number")
        number = int(dec)
    else:
        bad(field, "must be an integer")
    if minimum is not None and number < minimum:
        bad(field, "is below its minimum")
    if maximum is not None and number > maximum:
        bad(field, "is above its maximum")
    return number


# --------------------------------------------------------------------------
# decimals carrying two places
# --------------------------------------------------------------------------


def req_dec(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad(field, "is required")
    return _as_dec(data[field], field, minimum, maximum)


def opt_dec(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    return _as_dec(data[field], field, minimum, maximum)


def _as_dec(value, field, minimum, maximum):
    if isinstance(value, bool):
        bad(field, "must be a number")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            bad(field, "must be a number")
    else:
        bad(field, "must be a number")
    if dec != dec:  # NaN
        bad(field, "must be a number")
    dec = dec.quantize(TWO, rounding=ROUND_HALF_UP)
    if minimum is not None and dec < Decimal(minimum):
        bad(field, "is below its minimum")
    if maximum is not None and dec > Decimal(maximum):
        bad(field, "is above its maximum")
    return dec


# --------------------------------------------------------------------------
# enums, booleans, instants, lists
# --------------------------------------------------------------------------


def req_enum(data, field, allowed):
    if not present(data, field):
        bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad(field, "is not one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_bool(data, field):
    if not present(data, field):
        bad(field, "is required")
    if not isinstance(data[field], bool):
        bad(field, "must be a boolean")
    return data[field]


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_dt(data, field):
    if not present(data, field):
        bad(field, "is required")
    parsed = try_parse_dt(data[field])
    if parsed is None:
        bad(field, "must be an ISO 8601 UTC instant")
    return parsed


def opt_dt(data, field, default=None):
    if not present(data, field):
        return default
    return req_dt(data, field)


def req_id(data, field):
    if not present(data, field):
        bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be an identifier string")
    return value


def opt_id(data, field, default=None):
    if not present(data, field):
        return default
    return req_id(data, field)


def opt_enum_list(data, field, allowed, default=None):
    """A non-empty, duplicate-free subset of `allowed`."""
    if not present(data, field):
        return list(default) if default is not None else None
    value = data[field]
    if not isinstance(value, list) or len(value) == 0:
        bad(field, "must be a non-empty array")
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad(field, "contains an unknown value")
        if item in seen:
            bad(field, "contains duplicates")
        seen.append(item)
    return seen
