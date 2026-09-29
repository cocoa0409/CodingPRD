"""Schema-level request validation (ladder step 5) plus pagination parsing."""

from flask import request

from errors import ApiError
from util import parse_dt

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_MISSING = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        invalid("Request body must be valid JSON.")
    if not isinstance(payload, dict):
        invalid("Request body must be a JSON object.")
    return payload


def raw(body, key):
    return body.get(key, _MISSING)


def present(body, key):
    return key in body and body[key] is not None


def get_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        invalid("Field '%s' may not be below %d." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' may not exceed %d." % (key, maximum))
    return value


def get_str(body, key, required=True, default=None, min_len=None, max_len=None):
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        invalid("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' may not exceed %d characters." % (key, max_len))
    return value


def get_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def get_bool(body, key, required=False, default=None):
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % key)
    return value


def get_dt(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return default
    parsed = parse_dt(body[key])
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def get_id(body, key, required=True):
    """A nullable foreign-key string field."""
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return None
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        invalid("Field '%s' must be a resource identifier string." % key)
    return value


def get_optional_text(body, key):
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    return value


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        if str(limit) != raw_limit.strip():
            invalid("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            invalid(
                "Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        if str(offset) != raw_offset.strip():
            invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            invalid("Query parameter 'offset' may not be negative.")
    return limit, offset


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def filter_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    invalid("Query parameter '%s' must be a boolean." % name)


def filter_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        invalid("Query parameter '%s' must be an integer." % name)
    return parsed


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)
