"""Field presence/type checking (rank 7) and constraint checking (rank 8).

The two ladders are deliberately separate: every call site validates presence and
JSON type for the whole payload first, and only then validates constraints, so that
a request that is both mistyped and out of range reports ERR_INVALID_REQUEST.
"""

import re

from flask import request

import util
from constants import DEFAULT_LIMIT, MAX_LIMIT
from errors import ApiError

_MISSING = object()


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def invalid(message):
    return ApiError("ERR_VALIDATION_FAILED", message)


def json_body():
    """Parse the JSON body. A malformed or non-object body is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


# --- rank 7: presence and JSON type ------------------------------------------

def get_str(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    return value


def get_int(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    if not util.is_int(value):
        raise bad_request("Field '%s' must be an integer." % name)
    return util.as_int(value)


def get_bool(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def get_instant(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an RFC-3339 UTC instant string." % name)
    parsed = util.parse_instant(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an RFC-3339 UTC instant ending in Z." % name)
    return parsed


def get_array(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % name)
    return value


def get_id(data, name, required=True):
    """Foreign keys are strings; a missing or mistyped one is a rank-7 failure."""
    return get_str(data, name, required=required, default=None)


# --- rank 8: declared constraints ---------------------------------------------

def check_enum(value, name, allowed):
    if value is None:
        return value
    if value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def check_len(value, name, lo, hi, non_blank=False):
    if value is None:
        return value
    if len(value) < lo or len(value) > hi:
        raise invalid("Field '%s' must be between %d and %d characters." % (name, lo, hi))
    if non_blank and not value.strip():
        raise invalid("Field '%s' must not be blank." % name)
    return value


def check_pattern(value, name, pattern, description):
    if value is None:
        return value
    if not re.match(pattern, value):
        raise invalid("Field '%s' must contain %s." % (name, description))
    return value


def check_range(value, name, lo=None, hi=None):
    if value is None:
        return value
    if lo is not None and value < lo:
        raise invalid("Field '%s' must be at least %d." % (name, lo))
    if hi is not None and value > hi:
        raise invalid("Field '%s' must be at most %d." % (name, hi))
    return value


def check_before(earlier, later, message):
    if earlier is None or later is None:
        return
    if not (earlier < later):
        raise invalid(message)


def check_not_after(earlier, later, message):
    if earlier is None or later is None:
        return
    if earlier > later:
        raise invalid(message)


# --- pagination ---------------------------------------------------------------

def pagination():
    limit = DEFAULT_LIMIT
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > MAX_LIMIT:
            raise invalid("Query parameter 'limit' must be between 1 and %d." % MAX_LIMIT)
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' must not be negative.")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]


def filter_eq(rows, field, value, coerce=None):
    """Apply an optional equality filter; unknown values simply match nothing."""
    if value is None:
        return rows
    if coerce is not None:
        value = coerce(value)
    return [r for r in rows if r.get(field) == value]


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be a boolean." % name)
