"""Request-body well-formedness checks (PRD §2.9 layer 4).

All failures raise ERR_INVALID_REQUEST (400): missing required fields,
unparseable types/enums, violated conditional requirements, out-of-range
scalars. JSON booleans are never accepted where an integer is required.
"""

from flask import request

import timeutil as tu
from errors import ApiError, ERR_INVALID_REQUEST


def get_body():
    """Parsed JSON object body; an empty body parses as {} (action endpoints
    with no inputs), malformed/non-object JSON is a 400."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, msg)


def req_present(body, field):
    if field not in body:
        _bad(f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = req_present(body, field)
    if not isinstance(v, str) or not v:
        _bad(f"Field {field} must be a non-empty string.")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        _bad(f"Field {field} must be a string.")
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = req_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {field} must be an integer.")
    if min_v is not None and v < min_v:
        _bad(f"Field {field} must be >= {min_v}.")
    if max_v is not None and v > max_v:
        _bad(f"Field {field} must be <= {max_v}.")
    return v


def opt_int(body, field, default=None, min_v=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, min_v=min_v)


def req_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        _bad(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, bool):
        _bad(f"Field {field} must be a boolean.")
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if not isinstance(v, str) or v not in allowed:
        _bad(f"Field {field} must be one of {sorted(allowed)}.")
    return v


def req_month(body, field):
    v = req_present(body, field)
    if not tu.valid_month_str(v):
        _bad(f"Field {field} must be a YYYY-MM month identifier.")
    return v


def opt_month(body, field):
    """Optional YYYY-MM; explicit null maps to None, malformed is a 400."""
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not tu.valid_month_str(v):
        _bad(f"Field {field} must be a YYYY-MM month identifier or null.")
    return v


def req_month_nullable(body, field):
    """Required-but-nullable YYYY-MM: the key must be present; its value may
    be null (no pension) or a valid month identifier."""
    if field not in body:
        _bad(f"Missing required field: {field}")
    return opt_month(body, field)


def req_date(body, field):
    v = req_present(body, field)
    d = tu.parse_date_str(v)
    if d is None:
        _bad(f"Field {field} must be a YYYY-MM-DD date.")
    return v  # keep the canonical string form on the record


def opt_date(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if tu.parse_date_str(v) is None:
        _bad(f"Field {field} must be a YYYY-MM-DD date or null.")
    return v
