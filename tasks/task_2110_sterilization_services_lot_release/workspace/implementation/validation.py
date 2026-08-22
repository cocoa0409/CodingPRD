"""Payload-schema screening (validation priority 25) and pagination parsing."""

import json
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError

MISSING = object()


def body():
    raw = request.get_data(as_text=True) or ""
    if raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def _fail(field, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_string(data, field, min_len=1, max_len=None):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        _fail(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _fail(field, "must be at most %d characters" % max_len)
    return value


def opt_string(data, field, min_len=1, max_len=None, default=None):
    if field not in data or data[field] is None:
        return default
    return req_string(data, field, min_len, max_len)


def req_enum(data, field, allowed):
    value = req_string(data, field, 1, None)
    if value not in allowed:
        _fail(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def _as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer")
    return value


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    value = _as_int(data[field], field)
    if minimum is not None and value < minimum:
        _fail(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _fail(field, "must be <= %s" % maximum)
    return value


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def _as_decimal(value, field):
    if isinstance(value, bool):
        _fail(field, "must be a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    _fail(field, "must be a number")


def req_number(data, field, gt=None, ge=None, le=None, lt=None):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    value = _as_decimal(data[field], field)
    _range(value, field, gt, ge, le, lt)
    return value


def opt_number(data, field, gt=None, ge=None, le=None, lt=None, default=None):
    if field not in data or data[field] is None:
        return default
    return req_number(data, field, gt, ge, le, lt)


def _range(value, field, gt, ge, le, lt):
    if gt is not None and not value > gt:
        _fail(field, "must be > %s" % gt)
    if ge is not None and not value >= ge:
        _fail(field, "must be >= %s" % ge)
    if le is not None and not value <= le:
        _fail(field, "must be <= %s" % le)
    if lt is not None and not value < lt:
        _fail(field, "must be < %s" % lt)


def req_bool(data, field):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    if not isinstance(data[field], bool):
        _fail(field, "must be a boolean")
    return data[field]


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_bool(data, field)


def req_datetime(data, field):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    parsed = clock.parse_iso(data[field])
    if parsed is None:
        _fail(field, "must be an ISO 8601 timestamp")
    return parsed


def req_id(data, field):
    return req_string(data, field, 1, None)


def req_string_list(data, field, allowed):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    value = data[field]
    if not isinstance(value, list) or len(value) == 0:
        _fail(field, "must be a non-empty array")
    seen = set()
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            _fail(field, "members must be one of %s" % ", ".join(sorted(allowed)))
        if member in seen:
            _fail(field, "must not contain duplicates")
        seen.add(member)
    return list(value)


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset
