"""Request-shape validation (validation priority 3): required fields present,
types valid, enum members valid, conditional-required fields supplied. Every
failure raises ERR_INVALID_REQUEST (400).
"""
from flask import request

from core import clock
from core.errors import bad_request


def get_body():
    """Parse the request JSON body. Missing/malformed/non-object bodies are
    treated as an empty object for POST/PATCH (required-field checks then
    report ERR_INVALID_REQUEST), except a present-but-non-object JSON body,
    which is itself a shape error."""
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("request body must be a JSON object")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def req_str(data, name):
    value = data.get(name)
    if not isinstance(value, str) or value == "":
        raise bad_request("field '%s' is required and must be a string" % name)
    return value


def opt_str(data, name, default=None):
    value = data.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise bad_request("field '%s' must be a string" % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if not _is_int(value):
        raise bad_request("field '%s' is required and must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("field '%s' must be <= %s" % (name, maximum))
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    value = data.get(name)
    if value is None:
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_num(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if not _is_num(value):
        raise bad_request("field '%s' is required and must be a number" % name)
    if minimum is not None and value < minimum:
        raise bad_request("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("field '%s' must be <= %s" % (name, maximum))
    return value


def opt_num(data, name, default=None, minimum=None, maximum=None):
    value = data.get(name)
    if value is None:
        return default
    return req_num(data, name, minimum=minimum, maximum=maximum)


def req_enum(data, name, allowed):
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "field '%s' is required and must be one of %s" % (name, sorted(allowed))
        )
    return value


def opt_enum(data, name, allowed):
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("field '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def req_dt(data, name):
    value = data.get(name)
    dt = clock.parse_datetime(value)
    if dt is None:
        raise bad_request(
            "field '%s' is required and must be an ISO 8601 datetime" % name
        )
    return dt


def opt_dt(data, name, default=None):
    value = data.get(name)
    if value is None:
        return default
    return req_dt(data, name)


def req_str_list(data, name):
    value = data.get(name)
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise bad_request(
            "field '%s' is required and must be an array of strings" % name
        )
    return list(value)


def opt_str_list(data, name, default=None):
    value = data.get(name)
    if value is None:
        return default
    return req_str_list(data, name)


def req_capacity_map(data, name):
    value = data.get(name)
    if not isinstance(value, dict):
        raise bad_request(
            "field '%s' is required and must be an object mapping category codes "
            "to integer facing capacities" % name
        )
    out = {}
    for key, cap in value.items():
        if not isinstance(key, str) or key == "":
            raise bad_request("field '%s' keys must be category strings" % name)
        if not _is_int(cap) or cap < 0:
            raise bad_request(
                "field '%s' values must be integers >= 0" % name
            )
        out[key] = cap
    return out
