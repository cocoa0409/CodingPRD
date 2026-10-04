"""Input validation helpers."""
import errors as E
from decimal import Decimal, InvalidOperation


def body_json():
    from flask import request
    if not request.is_json:
        raise E.validation("request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise E.validation("request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise E.validation(f"missing required field: {name}")
    return data[name]


def opt_field(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return data[name]


def as_str(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise E.validation(f"missing required field: {name}")
        return None
    v = data[name]
    if not isinstance(v, str):
        raise E.validation(f"field {name} must be a string")
    return v


def as_bool(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise E.validation(f"missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise E.validation(f"field {name} must be a boolean")
    return v


def as_int(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise E.validation(f"missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise E.validation(f"field {name} must be an integer")
    return v


def as_number(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise E.validation(f"missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise E.validation(f"field {name} must be a number")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        raise E.validation(f"field {name} must be a number")


def as_enum(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise E.validation(f"missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, str):
        raise E.validation(f"field {name} must be a string")
    if v not in allowed:
        raise E.invalid_enum(f"field {name} carries an undeclared member: {v}")
    return v


def as_list(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise E.validation(f"missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, list):
        raise E.validation(f"field {name} must be an array")
    return v
