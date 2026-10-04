"""Request-shape validation helpers (validation pipeline stage 4).

All failures raise ERR_INVALID_REQUEST (400).
"""
from flask import request

from errors import bad_request
from util import parse_dt, to_decimal


def body_json():
    """Parse the request JSON body. Empty body -> {}. Malformed/non-object -> 400."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise bad_request("request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise bad_request(f"missing required field: {name}")
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, None)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str):
        raise bad_request(f"field {name} must be a string")
    return v


def as_enum(v, name, domain):
    if not isinstance(v, str) or v not in domain:
        raise bad_request(
            f"field {name} must be one of {sorted(domain)}"
        )
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"field {name} must be an integer")
    return v


def as_int_range(v, name, lo, hi):
    v = as_int(v, name)
    if v < lo or v > hi:
        raise bad_request(f"field {name} must be in [{lo}, {hi}]")
    return v


def as_number(v, name):
    try:
        return to_decimal(v)
    except ValueError:
        raise bad_request(f"field {name} must be a number")


def as_positive_number(v, name):
    d = as_number(v, name)
    if d <= 0:
        raise bad_request(f"field {name} must be greater than 0")
    return d


def as_dt(v, name):
    try:
        return parse_dt(v)
    except ValueError:
        raise bad_request(f"field {name} must be a valid ISO 8601 datetime")


def as_enum_list(v, name, domain):
    if (
        not isinstance(v, list)
        or len(v) == 0
        or any((not isinstance(x, str)) or x not in domain for x in v)
    ):
        raise bad_request(
            f"field {name} must be a non-empty array of values from {sorted(domain)}"
        )
    return list(v)


def check_window(open_dt, close_dt, open_name="window_open_utc", close_name="window_close_utc"):
    if not open_dt < close_dt:
        raise bad_request(f"{close_name} must be strictly after {open_name}")


def opt_enum_filter(args, name, domain):
    """Validate an optional query-string enum filter; returns None or the value."""
    v = args.get(name)
    if v is None:
        return None
    if v not in domain:
        raise bad_request(f"filter {name} must be one of {sorted(domain)}")
    return v


def parse_pagination(args):
    """limit (default 10, min 1, max 100), offset (default 0). Out-of-range
    values are clamped to the documented bounds; non-integers are 400."""
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
