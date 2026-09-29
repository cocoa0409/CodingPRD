"""Schema validation helpers -- admission ladder position 4 (ERR_INVALID_REQUEST)."""

import re

from flask import request

import db
from errors import ApiError

_MISSING = object()


def _fail(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Parse the request body as a JSON object. An absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        _fail("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _fail("Request body must be a JSON object.")
    return parsed


def present(body, name):
    return name in body and body[name] is not None


def forbid(body, name, message=None):
    if present(body, name):
        _fail(message or ("Field '%s' must be omitted." % name))


def _get(body, name, required):
    if not present(body, name):
        if required:
            _fail("Field '%s' is required." % name)
        return _MISSING
    return body[name]


def string(body, name, required=True, max_length=None, pattern=None, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % name)
    if value == "":
        _fail("Field '%s' must be a non-empty string." % name)
    if max_length is not None and len(value) > max_length:
        _fail("Field '%s' must be at most %d characters." % (name, max_length))
    if pattern is not None and not re.match(pattern, value):
        _fail("Field '%s' does not match the required format." % name)
    return value


def enum(body, name, choices, required=True, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % name)
    if value not in choices:
        _fail(
            "Field '%s' must be one of: %s." % (name, ", ".join(sorted(choices)))
        )
    return value


def integer(body, name, required=True, minimum=None, maximum=None, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be at most %s." % (name, maximum))
    return value


def number(body, name, required=True, minimum=None, maximum=None, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be at most %s." % (name, maximum))
    return value


def boolean(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % name)
    return value


def timestamp(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _fail("Field '%s' must be an ISO 8601 timestamp string." % name)
    parsed = db.parse_ts(value)
    if parsed is None:
        _fail(
            "Field '%s' must be an ISO 8601 UTC timestamp with a trailing Z." % name
        )
    return parsed


def query_enum(name, choices):
    """Validate an optional enum-valued query filter."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        _fail(
            "Query parameter '%s' must be one of: %s."
            % (name, ", ".join(sorted(choices)))
        )
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
