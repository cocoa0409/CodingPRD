"""Payload validation helpers."""

from db import parse_iso
from errors import invalid_request


def body_json():
    """Return parsed JSON body as dict; reject missing/non-object bodies."""
    from flask import request

    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise invalid_request(f"missing required field: {f}")


def req_string(data, field):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"field {field} must be a non-empty string")
    return v


def req_int(data, field, min_value=None, max_value=None):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    return as_int(v, field, min_value, max_value)


def as_int(v, field, min_value=None, max_value=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise invalid_request(f"field {field} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise invalid_request(f"field {field} must be <= {max_value}")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if v not in allowed:
        raise invalid_request(f"field {field} must be one of {sorted(allowed)}")
    return v


def req_bool(data, field):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if not isinstance(v, bool):
        raise invalid_request(f"field {field} must be a boolean")
    return v


def req_list(data, field, item_type=None):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if not isinstance(v, list):
        raise invalid_request(f"field {field} must be an array")
    if item_type is not None:
        for it in v:
            if not isinstance(it, item_type):
                raise invalid_request(f"field {field} items must be {item_type.__name__}")
    return v


def opt_int(data, field, default, min_value=None, max_value=None):
    if field not in data or data[field] is None:
        return default
    return as_int(data[field], field, min_value, max_value)


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise invalid_request(f"field {field} must be a boolean")
    return v


def opt_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if v not in allowed:
        raise invalid_request(f"field {field} must be one of {sorted(allowed)}")
    return v


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise invalid_request(f"field {field} must be a string")
    return v


def req_number(data, field, min_value=None, max_value=None):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    return as_number(v, field, min_value, max_value)


def as_number(v, field, min_value=None, max_value=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"field {field} must be a number")
    if min_value is not None and v < min_value:
        raise invalid_request(f"field {field} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise invalid_request(f"field {field} must be <= {max_value}")
    return v


def parse_iso_field(v, field):
    try:
        return parse_iso(v)
    except Exception:
        raise invalid_request(f"field {field} must be a valid ISO-8601 timestamp")
