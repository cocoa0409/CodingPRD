"""Request-shape validators (pipeline stage 6): required fields, enums, ranges.

All raise ERR_INVALID_REQUEST unless noted. Each getter returns the validated
value (dates return (canonical_str, date_obj)).
"""
from errors import ERR_INVALID_REQUEST, raise_err
import clock


def _bad(message):
    raise_err(ERR_INVALID_REQUEST, message)


def require_present(data, field):
    if field not in data or data[field] is None:
        _bad(f"Missing required field: {field}")
    return data[field]


def get_str(data, field, required=True, allow_empty=False):
    if field not in data or data[field] is None:
        if required:
            _bad(f"Missing required field: {field}")
        return None
    value = data[field]
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        _bad(f"Field {field} must be a non-empty string")
    return value


def get_int(data, field, required=True, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        if required:
            _bad(f"Missing required field: {field}")
        return None
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        _bad(f"Field {field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        _bad(f"Field {field} must be <= {maximum}")
    return value


def get_number(data, field, required=True):
    """A JSON number (int or float), preserved at input precision."""
    if field not in data or data[field] is None:
        if required:
            _bad(f"Missing required field: {field}")
        return None
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(f"Field {field} must be a number")
    return value


def get_enum(data, field, values, required=True):
    if field not in data or data[field] is None:
        if required:
            _bad(f"Missing required field: {field}")
        return None
    value = data[field]
    if value not in values:
        _bad(f"Field {field} must be one of {list(values)}")
    return value


def get_date(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            _bad(f"Missing required field: {field}")
        return None, None
    parsed = clock.parse_date(data[field])
    if parsed is None:
        _bad(f"Field {field} must be an ISO date (YYYY-MM-DD)")
    return parsed.isoformat(), parsed


def get_list(data, field, required=True, non_empty=False):
    if field not in data or data[field] is None:
        if required:
            _bad(f"Missing required field: {field}")
        return None
    value = data[field]
    if not isinstance(value, list) or (non_empty and not value):
        _bad(f"Field {field} must be a non-empty array")
    return value
