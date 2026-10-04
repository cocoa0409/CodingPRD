"""Shared request-validation helpers."""
from errors import err_input, ERR_INVALID_REQUEST


def get_json_body():
    from flask import request
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_input(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body, name):
    val = body.get(name)
    if val is None:
        raise err_input(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    if isinstance(val, str) and val.strip() == "":
        raise err_input(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if val not in allowed:
        raise err_input(ERR_INVALID_REQUEST,
                        "Invalid value for %s: %r" % (name, val))
    return val


def optional_enum(body, name, allowed):
    val = body.get(name)
    if val is None:
        return None
    if val not in allowed:
        raise err_input(ERR_INVALID_REQUEST,
                        "Invalid value for %s: %r" % (name, val))
    return val


def require_int(body, name, min_value=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_input(ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if min_value is not None and val < min_value:
        raise err_input(ERR_INVALID_REQUEST,
                        "%s must be >= %d" % (name, min_value))
    return val


def optional_int(body, name, default=None):
    val = body.get(name)
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_input(ERR_INVALID_REQUEST, "%s must be an integer" % name)
    return val


def require_number(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err_input(ERR_INVALID_REQUEST, "%s must be a number" % name)
    return val


def optional_number(body, name, default=None):
    val = body.get(name)
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err_input(ERR_INVALID_REQUEST, "%s must be a number" % name)
    return val


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise err_input(ERR_INVALID_REQUEST, "%s must be a string" % name)
    return val


def require_list(body, name):
    val = require_field(body, name)
    if not isinstance(val, list):
        raise err_input(ERR_INVALID_REQUEST, "%s must be an array" % name)
    return val


def optional_bool(body, name, default=None):
    val = body.get(name)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise err_input(ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return val
