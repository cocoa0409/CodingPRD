"""Priority-4 body-shape validation helpers and pagination parsing.

Every failure here raises ERR_VALIDATION (400). Type checks reject booleans
for numeric fields (Python's bool is an int subclass) and non-finite floats.
"""

import math

from flask import request

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import err
from timeutil import parse_iso


def body():
    """The request JSON object; absent/empty body behaves as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", "request body must be a JSON object")
    return data


def check_undeclared(data, allowed):
    extra = sorted(set(data) - set(allowed))
    if extra:
        err("ERR_VALIDATION", "undeclared field(s): " + ", ".join(extra))


def require(data, name):
    if name not in data:
        err("ERR_VALIDATION", "missing required field: " + name)
    return data[name]


def as_str(value, name):
    if not isinstance(value, str):
        err("ERR_VALIDATION", name + " must be a string")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_VALIDATION", name + " must be an integer")
    return value


def as_num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        err("ERR_VALIDATION", name + " must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        err("ERR_VALIDATION", name + " must be finite")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        err("ERR_VALIDATION", name + " must be a boolean")
    return value


def as_str_list(value, name):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        err("ERR_VALIDATION", name + " must be an array of strings")
    return value


def as_dt(value, name):
    if not isinstance(value, str):
        err("ERR_VALIDATION", name + " must be an ISO 8601 string")
    try:
        return parse_iso(value)
    except (ValueError, OverflowError):
        err("ERR_VALIDATION", name + " is not a valid ISO 8601 instant")


def as_enum(value, name, members):
    if not isinstance(value, str) or value not in members:
        err("ERR_VALIDATION", name + " must be one of " + ", ".join(members))
    return value


def pagination():
    """Parse limit/offset query params per PRD §2.3 (limit 1..100, default 10;
    offset >= 0, default 0). Out-of-range or unparsable -> ERR_VALIDATION."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            err("ERR_VALIDATION", "limit out of range [1, 100]")
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset
