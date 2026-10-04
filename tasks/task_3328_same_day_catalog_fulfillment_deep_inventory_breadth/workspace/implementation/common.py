"""Shared request-reading, pagination and serialization helpers."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import created_key, iso_millis, parse_iso
from errors import invalid_request, not_found

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN = 1
PAGINATION_MAX = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------- numerics


def round_half_up(value, places=0):
    """Round half away from zero, at the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------- request


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise invalid_request("Required field '%s' is missing." % field)
    return body[field]


def require_int(body, field, minimum=None, maximum=None):
    value = require(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.lstrip("-").isdigit():
            value = int(value)
        else:
            raise invalid_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise invalid_request("Field '%s' must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("Field '%s' must be <= %d." % (field, maximum))
    return value


def require_number(body, field, minimum=None, maximum=None):
    value = require(body, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("Field '%s' must be a number." % field)
    if minimum is not None and value < minimum:
        raise invalid_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("Field '%s' must be <= %s." % (field, maximum))
    return value


def require_str(body, field, allow_empty=False):
    value = require(body, field)
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be a string." % field)
    if not allow_empty and value == "":
        raise invalid_request("Field '%s' must not be empty." % field)
    return value


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is None:
            raise invalid_request("Required field '%s' is missing." % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise invalid_request("Field '%s' must be a boolean." % field)
    return value


def optional_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field '%s' must be an integer." % field)
    return value


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be a string." % field)
    return value


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise invalid_request("Field '%s' must be a boolean." % field)
    return value


def filter_list(rows, args, fields):
    """Apply exact-match query filters for the named fields, then order."""
    result = []
    for row in rows:
        keep = True
        for field in fields:
            value = args.get(field)
            if value is None or value == "":
                continue
            if row.get(field) != value:
                keep = False
                break
        if keep:
            result.append(row)
    return result


# ---------------------------------------------------------------- pagination


def pagination():
    """limit / offset with the declared defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = PAGINATION_DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise invalid_request("Query parameter 'limit' must be an integer.")
    try:
        offset = PAGINATION_DEFAULT_OFFSET if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise invalid_request("Query parameter 'offset' must be an integer.")
    if limit < PAGINATION_MIN or limit > PAGINATION_MAX:
        raise invalid_request(
            "Query parameter 'limit' must be between %d and %d."
            % (PAGINATION_MIN, PAGINATION_MAX)
        )
    if offset < 0:
        raise invalid_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def page(items, limit, offset):
    """Deterministic ordering (created_at ASC) then windowing."""
    ordered = sorted(items, key=created_key)
    return ordered[offset:offset + limit], len(ordered)


def query_flag(name):
    """Read an optional boolean-ish query filter; None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in ("true", "1", "yes")


# ---------------------------------------------------------------- lookup


def find(store_dict, key, error_id, message):
    record = store_dict.get(key)
    if record is None:
        raise not_found(error_id, message)
    return record


def parse_clock(value, field="current_utc"):
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise invalid_request("Field '%s' must be an ISO 8601 UTC timestamp." % field)


def parse_optional_datetime(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be an ISO 8601 timestamp." % field)
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise invalid_request("Field '%s' must be an ISO 8601 timestamp." % field)


def out_iso(dt):
    return iso_millis(dt) if dt is not None else None