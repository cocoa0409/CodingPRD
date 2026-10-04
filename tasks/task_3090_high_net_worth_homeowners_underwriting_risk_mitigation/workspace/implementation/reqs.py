"""Request-body parsing, validation and pagination helpers (PRD §2.3, §2.11)."""

from flask import request

from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

TRUE_VALUES = {"true", "1", "yes", "y", "t"}
FALSE_VALUES = {"false", "0", "no", "n", "f"}


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def require(data, field):
    """A required input field that is absent is ERR_INVALID_REQUEST (PRD §2.11)."""
    if field not in data or data[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    return data[field]


def enum(data, field, allowed, default=None, required=True):
    if field not in data or data[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = data[field]
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (field, sorted(allowed)))
    return value


def integer(data, field, default=None, minimum=None, required=False, strict_min=False):
    if field not in data or data[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None:
        if strict_min and value <= minimum:
            raise err("ERR_INVALID_REQUEST", "Field %s must be greater than %s." % (field, minimum))
        if not strict_min and value < minimum:
            raise err("ERR_INVALID_REQUEST", "Field %s must be at least %s." % (field, minimum))
    return value


def number(data, field, default=None, minimum=None, strict_min=False, maximum=None,
           required=False):
    if field not in data or data[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    if minimum is not None:
        if strict_min and value <= minimum:
            raise err("ERR_INVALID_REQUEST", "Field %s must be greater than %s." % (field, minimum))
        if not strict_min and value < minimum:
            raise err("ERR_INVALID_REQUEST", "Field %s must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be at most %s." % (field, maximum))
    return value


def boolean(data, field, default=False, required=False):
    if field not in data or data[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = data[field]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in TRUE_VALUES:
            return True
        if low in FALSE_VALUES:
            return False
    raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)


def string(data, field, default=None, required=False):
    if field not in data or data[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = data[field]
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return value


def pagination():
    """Read limit/offset from the query string (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST",
                      "limit must be between %d and %d."
                      % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def query(field):
    return request.args.get(field)


def sorted_by_created(records):
    """Every list is ascending by created_at unless a rule says otherwise."""
    return sorted(records, key=lambda r: r["created_at"])