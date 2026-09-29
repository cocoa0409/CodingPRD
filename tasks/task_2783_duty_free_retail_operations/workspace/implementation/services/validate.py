"""Tier 5 request well-formedness helpers (PRD section 2.8)."""
import re

import clock
from errors import ApiError

UPPER2 = re.compile(r"^[A-Z]{2}$")
UPPER3 = re.compile(r"^[A-Z]{3}$")
PERIOD_CODE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, pattern=None, allow_empty=False):
    if not present(body, name):
        invalid("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        invalid("Field '%s' must not be empty." % name)
    if pattern is not None and not pattern.match(value):
        invalid("Field '%s' has an invalid format." % name)
    return value


def opt_string(body, name, pattern=None, default=None):
    if not present(body, name):
        return default
    return req_string(body, name, pattern=pattern)


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not present(body, name):
        invalid("Field '%s' is required." % name)
    value = _as_int(name, body[name])
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        invalid("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def opt_bool(body, name, default=False):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def req_ts(body, name):
    raw = req_string(body, name)
    try:
        return clock.parse(raw)
    except (ValueError, TypeError):
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)


def opt_ts(body, name, default=None):
    if not present(body, name):
        return default
    return req_ts(body, name)
