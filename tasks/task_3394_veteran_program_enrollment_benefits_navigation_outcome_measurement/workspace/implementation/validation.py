"""Request well-formedness validation (priority 2 in PRD section 2.7) and
pagination parameter parsing (PRD section 2.3)."""
from flask import request

from db import parse_iso
from errors import ApiError


def _bad(field, reason):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, reason), 400)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _bad("body", "must be a JSON object")
    return data


def req_str(body, field):
    if field not in body or body[field] is None:
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    return value


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    return value


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        _bad(field, "is not one of the declared values")
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def _int_value(value, field, minimum, maximum, choices):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if choices is not None and value not in choices:
        _bad(field, "is not one of the allowed values")
    if minimum is not None and value < minimum:
        _bad(field, "is below the minimum of %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "exceeds the maximum of %s" % maximum)
    return value


def req_int(body, field, minimum=None, maximum=None, choices=None):
    if field not in body or body[field] is None:
        _bad(field, "is required")
    return _int_value(body[field], field, minimum, maximum, choices)


def opt_int(body, field, default=None, minimum=None, maximum=None, choices=None):
    if field not in body or body[field] is None:
        return default
    return _int_value(body[field], field, minimum, maximum, choices)


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def req_dt(body, field):
    if field not in body or body[field] is None:
        _bad(field, "is required")
    dt = parse_iso(body[field])
    if dt is None:
        _bad(field, "must be an ISO 8601 datetime")
    return dt


def opt_dt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    dt = parse_iso(body[field])
    if dt is None:
        _bad(field, "must be an ISO 8601 datetime")
    return dt


def opt_enum_list(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return list(default) if default is not None else []
    value = body[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad(field, "contains a value outside the declared set")
    return list(value)


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset
