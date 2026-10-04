"""Request-body validators.

A malformed request — a required field missing, an enum value outside its
declared set, a conditional-field rule violated, or a numeric range violated —
is rejected with ERR_INVALID_REQUEST (PRD section 2.8).
"""

from flask import request

from errors import api_error


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise api_error(
            "ERR_INVALID_REQUEST", "request body must be a JSON object"
        )
    return data


def _fail(message):
    raise api_error("ERR_INVALID_REQUEST", message)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, name):
    value = body.get(name)
    if not isinstance(value, str) or value == "":
        _fail("field '%s' is required and must be a non-empty string" % name)
    return value


def opt_str(body, name):
    if name not in body or body.get(name) is None:
        return None
    value = body.get(name)
    if not isinstance(value, str):
        _fail("field '%s' must be a string" % name)
    return value


def req_int(body, name, minimum=None):
    if name not in body or body.get(name) is None:
        _fail("field '%s' is required" % name)
    value = body.get(name)
    if not _is_int(value):
        _fail("field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        _fail("field '%s' must be >= %d" % (name, minimum))
    return value


def opt_int(body, name, minimum=None):
    if name not in body or body.get(name) is None:
        return None
    return req_int(body, name, minimum)


def req_bool(body, name):
    if name not in body or body.get(name) is None:
        _fail("field '%s' is required" % name)
    value = body.get(name)
    if not isinstance(value, bool):
        _fail("field '%s' must be a boolean" % name)
    return value


def opt_bool(body, name):
    if name not in body or body.get(name) is None:
        return None
    value = body.get(name)
    if not isinstance(value, bool):
        _fail("field '%s' must be a boolean" % name)
    return value


def req_enum(body, name, allowed):
    value = body.get(name)
    if not isinstance(value, str) or value not in allowed:
        _fail(
            "field '%s' is required and must be one of: %s"
            % (name, ", ".join(allowed))
        )
    return value


def req_list_of_str(body, name):
    if name not in body or body.get(name) is None:
        _fail("field '%s' is required" % name)
    value = body.get(name)
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        _fail("field '%s' must be an array of strings" % name)
    return value
