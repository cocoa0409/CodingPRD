"""Request body parsing and field validators.

All failures here are validation-precedence step 4 (ERR_INVALID_REQUEST,
HTTP 400): required fields present, types correct, enum members valid,
integer ranges honored.
"""

from datetime import datetime, timezone

from flask import request

from errors import fail

_MISSING = object()


def body_json(required=False):
    """Return the request JSON body as a dict.

    With required=True a missing/non-object body fails step 4.
    """
    data = request.get_json(silent=True)
    if data is None:
        if required:
            fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _invalid(field, why):
    fail("ERR_INVALID_REQUEST", f"field '{field}': {why}")


def f_str(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _invalid(field, "required field is missing")
    if not isinstance(v, str):
        _invalid(field, "must be a string")
    return v


def f_int(body, field, minimum=None, maximum=None):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _invalid(field, "required field is missing")
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(field, "must be an integer")
    if minimum is not None and v < minimum:
        _invalid(field, f"must be >= {minimum}")
    if maximum is not None and v > maximum:
        _invalid(field, f"must be <= {maximum}")
    return v


def f_bool(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _invalid(field, "required field is missing")
    if not isinstance(v, bool):
        _invalid(field, "must be a boolean")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        return default
    if not isinstance(v, bool):
        _invalid(field, "must be a boolean")
    return v


def f_enum(body, field, allowed):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _invalid(field, "required field is missing")
    if not isinstance(v, str) or v not in allowed:
        _invalid(field, f"must be one of {sorted(allowed)}")
    return v


def parse_datetime_value(v, field):
    """Parse an ISO 8601 instant. Accepts 'Z' or numeric offsets, with or
    without fractional seconds. Naive values are assumed UTC."""
    if not isinstance(v, str):
        _invalid(field, "must be an ISO 8601 datetime string")
    s = v.strip()
    if not s:
        _invalid(field, "must be an ISO 8601 datetime string")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _invalid(field, "must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f_dt(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _invalid(field, "required field is missing")
    return parse_datetime_value(v, field)


def f_list(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _invalid(field, "required field is missing")
    if not isinstance(v, list):
        _invalid(field, "must be an array")
    return v
