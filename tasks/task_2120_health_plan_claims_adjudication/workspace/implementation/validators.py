"""Request-body validation helpers.

Check 6 of PRD 2.8 (required fields, ERR_MISSING_REQUIRED_FIELD) always runs
before check 7 (field well-formedness, ERR_INVALID_FIELD_VALUE), so callers
invoke require_fields() first and the typed readers afterwards.
"""

from flask import request

from errors import ApiError
from store import parse_date


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def require_fields(payload, fields):
    for field in fields:
        if field not in payload or payload[field] is None:
            raise ApiError(
                "ERR_MISSING_REQUIRED_FIELD", "Required field '%s' is missing." % field
            )


def _invalid(field):
    raise ApiError("ERR_INVALID_FIELD_VALUE", "Field '%s' is not well formed." % field)


def read_string(payload, field, default=None, required=False):
    if field not in payload or payload[field] is None:
        if required:
            _invalid(field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        _invalid(field)
    return value


def read_int(payload, field, default=None, minimum=None, maximum=None, required=False):
    if field not in payload or payload[field] is None:
        if required:
            _invalid(field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(field)
    if minimum is not None and value < minimum:
        _invalid(field)
    if maximum is not None and value > maximum:
        _invalid(field)
    return value


def read_number(payload, field, default=None, minimum=None, maximum=None,
                exclusive_minimum=None, required=False):
    if field not in payload or payload[field] is None:
        if required:
            _invalid(field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(field)
    value = float(value)
    if minimum is not None and value < minimum:
        _invalid(field)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _invalid(field)
    if maximum is not None and value > maximum:
        _invalid(field)
    return value


def read_enum(payload, field, members, default=None, required=False):
    if field not in payload or payload[field] is None:
        if required:
            _invalid(field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        _invalid(field)
    return value


def read_date(payload, field, default=None, required=False):
    if field not in payload or payload[field] is None:
        if required:
            _invalid(field)
        return default
    value = payload[field]
    if parse_date(value) is None:
        _invalid(field)
    return value


def check_interval(field, start, end):
    """An interval's end may not precede its start (PRD 2.6)."""
    if start is None or end is None:
        return
    if end < start:
        _invalid(field)
