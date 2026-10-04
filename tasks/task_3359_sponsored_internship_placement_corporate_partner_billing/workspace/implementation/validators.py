"""Request-body readers.  Every failure is ERR_INVALID_REQUEST (422).

These helpers only ever raise the well-formedness error: the request body must
carry the required fields, enums must name a declared member and numeric fields
must be of the right shape (PRD 2.5, check 5).
"""

from flask import request

import timeutil
from errors import ERR_INVALID_REQUEST, ApiError


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def fail(message):
    raise ApiError(ERR_INVALID_REQUEST, message, 422)


def _present(data, name):
    return name in data and data[name] is not None


def as_str(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("field '%s' is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("field '%s' must be a non-empty string" % name)
    return value.strip()


def as_enum(data, name, allowed, required=True, default=None):
    value = as_str(data, name, required=required, default=default)
    if value is None:
        return None
    if value not in allowed:
        fail("field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def as_int(data, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            fail("field '%s' is required" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            fail("field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("field '%s' must be at most %s" % (name, maximum))
    return value


def as_number(data, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            fail("field '%s' is required" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("field '%s' must be a number" % name)
    value = float(value)
    if minimum is not None and value < minimum:
        fail("field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("field '%s' must be at most %s" % (name, maximum))
    return value


def request_arg(name):
    """Optional query-string filter value; absent/blank means no filter."""
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def as_dt(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("field '%s' is required" % name)
        return default
    parsed = timeutil.parse_dt(data[name])
    if parsed is None:
        fail("field '%s' must be an ISO 8601 timestamp" % name)
    return parsed
