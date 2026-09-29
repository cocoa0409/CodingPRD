"""Request-shape validation (PRD 2.7, priority 6): required fields, declared
enum members, integral _cents/_bps amounts inside their range, parseable
ISO 8601 instants."""

from flask import request

import core
from errors import ApiError


def _invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON request body as a dict; a missing or non-object body reads {}."""
    try:
        raw = request.get_json(silent=True, force=True)
    except Exception:
        raw = None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _invalid("The request body must be a JSON object.")
    return raw


def present(data, name):
    return name in data and data[name] is not None


def req_field(data, name):
    if not present(data, name):
        raise _invalid("%s is required." % name)
    return data[name]


def req_string(data, name):
    value = req_field(data, name)
    if not isinstance(value, str) or not value.strip():
        raise _invalid("%s must be a non-empty string." % name)
    return value


def opt_string(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        raise _invalid("%s must be a string." % name)
    return value


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise _invalid("%s is below its permitted range." % name)
    if maximum is not None and value > maximum:
        raise _invalid("%s is above its permitted range." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    return _check_int(name, req_field(data, name), minimum, maximum)


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    return _check_int(name, data[name], minimum, maximum)


def req_bool(data, name):
    value = req_field(data, name)
    if not isinstance(value, bool):
        raise _invalid("%s must be a boolean." % name)
    return value


def req_enum(data, name, members):
    value = req_field(data, name)
    if not isinstance(value, str) or value not in members:
        raise _invalid("%s must be one of %s." % (name, ", ".join(sorted(members))))
    return value


def opt_enum(data, name, members, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, members)


def req_instant(data, name):
    value = req_field(data, name)
    parsed = core.parse_instant(value)
    if parsed is None:
        raise _invalid("%s must be a parseable ISO 8601 UTC instant." % name)
    return parsed


def opt_instant(data, name, default=None):
    if not present(data, name):
        return default
    return req_instant(data, name)


def req_list(data, name):
    value = req_field(data, name)
    if not isinstance(value, list):
        raise _invalid("%s must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            raise _invalid("%s must be an array of strings." % name)
    return list(value)


def opt_id(data, name):
    """An optional foreign-key string; explicit null reads as absent."""
    if not present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        raise _invalid("%s must be a string identifier." % name)
    return value


def req_id(data, name):
    value = req_field(data, name)
    if not isinstance(value, str) or not value.strip():
        raise _invalid("%s must be a string identifier." % name)
    return value
