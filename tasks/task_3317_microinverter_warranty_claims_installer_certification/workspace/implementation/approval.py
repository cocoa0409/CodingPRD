"""Request-body reading and the structural assertions behind
ERR_INVALID_REQUEST_BODY (PRD section 2.5, priority 3).

Required-field presence, type checking and enum/range checking live here so the
route modules stay declarative.
"""

from flask import request

from errors import fail
from respond import is_iso, parse_iso

MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST_BODY", "the request body must be a JSON object")
    return data


def raw(data, name, default=MISSING):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return value


def required(data, name):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
    return value


def as_str(data, name, required_=True, default=None, allow_blank=False):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be a string" % name)
    if not allow_blank and value.strip() == "":
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "field `%s` must not be empty" % name)
        return default
    return value


def as_nonempty_str_optional(data, name):
    """Optional string that must be non-empty when supplied (e.g. a reason)."""
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be a non-empty string" % name)
    return value


def as_enum(data, name, allowed, required_=True, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST_BODY",
             "field `%s` must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def as_number(data, name, required_=True, default=None, minimum=None,
              maximum=None, exclusive_minimum=None, allow_zero=True):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be a number" % name)
    value = float(value)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` is out of range" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` is out of range" % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` is out of range" % name)
    return value


def as_int(data, name, required_=True, default=None, minimum=None,
           exclusive_minimum=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be an integer" % name)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` is out of range" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` is out of range" % name)
    return value


def as_bool(data, name, required_=False, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be a boolean" % name)
    return value


def as_instant(data, name, required_=True, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if not is_iso(value):
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be an ISO 8601 instant" % name)
    return parse_iso(value)


def as_array(data, name, required_=True, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        if required_:
            fail("ERR_INVALID_REQUEST_BODY", "missing required field `%s`" % name)
        return default
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST_BODY", "field `%s` must be an array" % name)
    return value
