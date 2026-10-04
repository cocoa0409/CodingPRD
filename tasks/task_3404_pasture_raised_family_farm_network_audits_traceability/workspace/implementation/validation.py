"""Request body and query-parameter validation helpers.

All failures here raise ERR_INVALID_REQUEST (400), the priority-6
"well-formed body" tier of PRD 2.11. Field extractors return the sentinel
MISSING for absent optional fields.
"""
import math

from flask import request

import constants as C
from clock import parse_date, parse_datetime
from errors import ApiError

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def get_body():
    """JSON object body; absent body reads as {} (endpoints without required
    fields tolerate it), non-object JSON is a 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _bad("request body must be a JSON object")
    return data


def f_str(data, name, required=True):
    v = data.get(name, MISSING)
    if v is MISSING:
        if required:
            _bad("missing required field: %s" % name)
        return MISSING
    if not isinstance(v, str) or len(v) == 0:
        _bad("field %s must be a non-empty string" % name)
    return v


def f_int(data, name, required=True, minimum=None):
    v = data.get(name, MISSING)
    if v is MISSING:
        if required:
            _bad("missing required field: %s" % name)
        return MISSING
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        _bad("field %s must be >= %d" % (name, minimum))
    return v


def f_num(data, name, required=True, minimum=None, min_exclusive=False, maximum=None):
    v = data.get(name, MISSING)
    if v is MISSING:
        if required:
            _bad("missing required field: %s" % name)
        return MISSING
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("field %s must be a number" % name)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        _bad("field %s must be a finite number" % name)
    if minimum is not None:
        if min_exclusive and not (v > minimum):
            _bad("field %s must be > %s" % (name, minimum))
        if not min_exclusive and v < minimum:
            _bad("field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        _bad("field %s must be <= %s" % (name, maximum))
    return v


def f_enum(data, name, allowed, required=True):
    v = data.get(name, MISSING)
    if v is MISSING:
        if required:
            _bad("missing required field: %s" % name)
        return MISSING
    if not isinstance(v, str) or v not in allowed:
        _bad("field %s must be one of: %s" % (name, ", ".join(allowed)))
    return v


def f_date(data, name, required=True):
    """-> (raw_string, parsed_date); validates strict YYYY-MM-DD."""
    v = data.get(name, MISSING)
    if v is MISSING:
        if required:
            _bad("missing required field: %s" % name)
        return (MISSING, MISSING)
    d = parse_date(v)
    if d is None:
        _bad("field %s must be a valid YYYY-MM-DD date" % name)
    return (v, d)


def f_datetime(data, name, required=True):
    """-> (raw_string, parsed_utc_datetime)."""
    v = data.get(name, MISSING)
    if v is MISSING:
        if required:
            _bad("missing required field: %s" % name)
        return (MISSING, MISSING)
    dt = parse_datetime(v)
    if dt is None:
        _bad("field %s must be a valid ISO 8601 datetime" % name)
    return (v, dt)


def pagination():
    """PRD 2.3: limit default 10 (min 1, max 100), offset default 0 (>= 0)."""
    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = C.PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            _bad("limit must be an integer")
        if limit < C.PAGE_LIMIT_MIN or limit > C.PAGE_LIMIT_MAX:
            _bad("limit must be between %d and %d" % (C.PAGE_LIMIT_MIN, C.PAGE_LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is None:
        offset = C.PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset
