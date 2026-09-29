"""Request-shape validation (validation priority 3 -> ERR_INVALID_REQUEST)."""
import datetime

from flask import request

import db
from errors import fail

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_MISSING = object()


def bad(message):
    fail("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; an absent body is treated as {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(payload, field):
    return field in payload and payload[field] is not None


def req(payload, field):
    if not _present(payload, field):
        bad("Field '%s' is required." % field)
    return payload[field]


def str_field(payload, field, min_len=1, max_len=None, required=True, default=None):
    if not _present(payload, field):
        if required:
            bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (field, max_len))
    return value


def enum_field(payload, field, members, required=True, default=None):
    if not _present(payload, field):
        if required:
            bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def int_field(payload, field, low=None, high=None, required=True, default=None):
    if not _present(payload, field):
        if required:
            bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if low is not None and value < low:
        bad("Field '%s' must be >= %d." % (field, low))
    if high is not None and value > high:
        bad("Field '%s' must be <= %d." % (field, high))
    return value


def bool_field(payload, field, required=True, default=None):
    if not _present(payload, field):
        if required:
            bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def date_field(payload, field, required=True, default=None):
    if not _present(payload, field):
        if required:
            bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or len(value) != 10:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % field)
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % field)
    return value


def enum_array_field(payload, field, members, required=True):
    if not _present(payload, field):
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = payload[field]
    if not isinstance(value, list) or len(value) == 0:
        bad("Field '%s' must be a non-empty array." % field)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in members:
            bad("Field '%s' members must be one of %s." % (field, ", ".join(members)))
        if item in seen:
            bad("Field '%s' members must be distinct." % field)
        seen.add(item)
    return list(value)


def ordering(first, second, first_name, second_name, strict=False):
    """second must be > first (strict) or >= first (non-strict)."""
    if strict:
        if not second > first:
            bad("%s must be strictly greater than %s." % (second_name, first_name))
    else:
        if second < first:
            bad("%s must be on or after %s." % (second_name, first_name))


def unique_field(collection, field, value):
    for row in getattr(db.db, collection).values():
        if row.get(field) == value:
            bad("Field '%s' must be unique." % field)


# ---------------------------------------------------------------- query params

def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def q_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    if len(value) != 10:
        bad("Query parameter '%s' must be a YYYY-MM-DD calendar date." % name)
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        bad("Query parameter '%s' must be a YYYY-MM-DD calendar date." % name)
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total
