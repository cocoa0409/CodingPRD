"""Request body parsing and schema validation (ERR_INVALID_REQUEST, PRD section 2.10 step 7)."""
from __future__ import annotations

from flask import request

from calc import parse_instant
from errors import ApiError

MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON request body. An absent or empty body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise bad("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object")
    return parsed


def present(payload, field):
    return field in payload and payload[field] is not None


def require_present(payload, field):
    if field not in payload or payload[field] is None:
        raise bad("%s is required" % field)
    return payload[field]


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(payload, field, minimum=None, maximum=None):
    value = require_present(payload, field)
    if not is_int(value):
        raise bad("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise bad("%s must be at least %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("%s must be at most %s" % (field, maximum))
    return value


def opt_int(payload, field, default, minimum=None, maximum=None):
    if not present(payload, field):
        if field in payload and payload[field] is None:
            raise bad("%s may not be null" % field)
        return default
    return req_int(payload, field, minimum, maximum)


def req_str(payload, field, min_len=1, max_len=None):
    value = require_present(payload, field)
    if not isinstance(value, str):
        raise bad("%s must be a string" % field)
    if min_len is not None and len(value.strip()) < min_len:
        raise bad("%s must not be blank" % field)
    if min_len is not None and len(value) < min_len:
        raise bad("%s is too short" % field)
    if max_len is not None and len(value) > max_len:
        raise bad("%s is too long" % field)
    return value


def opt_str(payload, field, default=None, min_len=1, max_len=None):
    if not present(payload, field):
        return default
    return req_str(payload, field, min_len, max_len)


def req_enum(payload, field, allowed):
    value = require_present(payload, field)
    if not isinstance(value, str) or value not in allowed:
        raise bad("%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def req_bool(payload, field, default):
    if not present(payload, field):
        if field in payload and payload[field] is None:
            raise bad("%s may not be null" % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        raise bad("%s must be a boolean" % field)
    return value


def req_instant(payload, field):
    value = require_present(payload, field)
    moment = parse_instant(value)
    if moment is None:
        raise bad("%s must be an ISO 8601 UTC instant" % field)
    return moment


def req_id(payload, field):
    """A foreign key field: present, non-null and a string."""
    value = require_present(payload, field)
    if not isinstance(value, str) or not value.strip():
        raise bad("%s must be an identifier string" % field)
    return value


def raw_id(payload, field):
    """Fetch a foreign key for reference resolution before schema validation.

    Returns MISSING when the caller did not supply a usable identifier, so that the
    schema stage can report the failure in its own precedence group.
    """
    if field not in payload or payload[field] is None:
        return MISSING
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        return MISSING
    return value
