"""Request body / query schema validation (priority 5: ERR_INVALID_REQUEST)."""
from flask import request

from errors import ApiError
from util import parse_dt, parse_date
import response

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def present(b, key):
    return key in b and b[key] is not None


# ------------------------------------------------------------------ scalars

def get_str(b, key, required=True, default=None, min_len=1, max_len=None,
            allow_blank=False):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    value = b[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % key)
    if not allow_blank and not value.strip():
        bad("Field '%s' must not be blank" % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short" % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long" % key)
    return value


def get_enum(b, key, values, required=True, default=None):
    value = get_str(b, key, required=required, default=MISSING)
    if value is MISSING:
        return default
    if value not in values:
        bad("Field '%s' must be one of %s" % (key, ", ".join(values)))
    return value


def get_int(b, key, required=True, default=None, minimum=None, maximum=None):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (key, maximum))
    return value


def get_num(b, key, required=True, default=None, minimum=None, maximum=None,
            exclusive_minimum=None):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % key)
    value = float(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (key, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        bad("Field '%s' must be greater than %s" % (key, exclusive_minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (key, maximum))
    return value


def get_bool(b, key, required=True, default=None):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    value = b[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % key)
    return value


def get_dt(b, key, required=True, default=None):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    value = b[key]
    parsed = parse_dt(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp" % key)
    return parsed


def get_date(b, key, required=True, default=None):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    parsed = parse_date(b[key])
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD date" % key)
    return parsed


def get_list(b, key, required=True, default=None):
    if not present(b, key):
        if required:
            bad("Field '%s' is required" % key)
        return default
    value = b[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % key)
    return value


# ------------------------------------------------------------- foreign keys

def fk(b, key, collection, error_id):
    """Priority 4: resolve a body foreign key, 404 family error when unknown."""
    value = b.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    row = collection.get(value)
    if row is None:
        raise ApiError(error_id)
    return row


def path_row(collection, row_id, error_id):
    """Priority 3: path segment resolution, left to right."""
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# ------------------------------------------------------------- query params

def pagination():
    args = request.args
    limit = response.PAGINATION_DEFAULT_LIMIT
    offset = response.PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer")
        if limit < response.PAGINATION_MIN_LIMIT or limit > response.PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must be between %d and %d"
                % (response.PAGINATION_MIN_LIMIT, response.PAGINATION_MAX_LIMIT))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0")
    return limit, offset


def query_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
