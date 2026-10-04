"""Request-body helpers.

PRD section 2.11 rank 1 refuses a body that is missing a required input field or
supplies one with a value of the wrong type, reported as ERR_INVALID_REQUEST.
The functions here are the single place that check happens.
"""

from flask import request

from errors import ERR_INVALID_REQUEST, fail


def json_body():
    """The request body as a dict; an absent or non-object body is an empty dict."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return body


def as_str(value, required=False, name=None):
    if value is None:
        if required:
            fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
        return None
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field %r must be a string." % name)
    return value


def require_str(body, name):
    if name not in body:
        fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
    value = body[name]
    if value is None or not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field %r must be a non-empty string." % name)
    return value


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field %r must be a string." % name)
    return value


def as_int(value, required=False, name=None, default=None):
    if value is None:
        if required:
            fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, "Field %r must be an integer." % name)
    if isinstance(value, float) and value != int(value):
        fail(ERR_INVALID_REQUEST, "Field %r must be an integer." % name)
    return int(value)


def require_int(body, name):
    if name not in body:
        fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
    return as_int(body[name], required=True, name=name)


def opt_int(body, name, default=None):
    return as_int(body.get(name), name=name, default=default)


def as_number(value, required=False, name=None, default=None):
    if value is None:
        if required:
            fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, "Field %r must be a number." % name)
    return float(value)


def require_number(body, name):
    if name not in body:
        fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
    return as_number(body[name], required=True, name=name)


def opt_number(body, name, default=None):
    return as_number(body.get(name), name=name, default=default)


def as_bool(value, required=False, name=None, default=None):
    if value is None:
        if required:
            fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
        return default
    if not isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, "Field %r must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    return as_bool(body.get(name), name=name, default=default)


def require_list(body, name):
    if name not in body:
        fail(ERR_INVALID_REQUEST, "Field %r is required." % name)
    value = body[name]
    if not isinstance(value, list):
        fail(ERR_INVALID_REQUEST, "Field %r must be an array." % name)
    return value


def require_enum(body, name, allowed):
    value = require_str(body, name)
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "Field %r must be one of %s." % (name, list(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    value = opt_str(body, name, None)
    if value is None:
        return default
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "Field %r must be one of %s." % (name, list(allowed)))
    return value


def require_enum_ci(body, name, allowed):
    """Enum helper that tolerates lower-case input and canonicalises it."""
    value = require_str(body, name)
    upper = value.upper()
    if upper in allowed:
        return upper
    if value in allowed:
        return value
    fail(ERR_INVALID_REQUEST, "Field %r must be one of %s." % (name, list(allowed)))


def opt_enum_ci(body, name, allowed, default=None):
    value = opt_str(body, name, None)
    if value is None:
        return default
    upper = value.upper()
    if upper in allowed:
        return upper
    if value in allowed:
        return value
    fail(ERR_INVALID_REQUEST, "Field %r must be one of %s." % (name, list(allowed)))


def require_datetime(body, name):
    from db import parse_dt

    raw = require_str(body, name)
    dt = parse_dt(raw)
    if dt is None:
        fail(ERR_INVALID_REQUEST, "Field %r must be an ISO 8601 instant." % name)
    return dt


def opt_datetime(body, name, default=None):
    from db import parse_dt

    raw = opt_str(body, name, None)
    if raw is None:
        return default
    dt = parse_dt(raw)
    if dt is None:
        fail(ERR_INVALID_REQUEST, "Field %r must be an ISO 8601 instant." % name)
    return dt


# --------------------------------------------------------------------------
# Query-string helpers
# --------------------------------------------------------------------------
def query_enum(name, allowed, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        fail(ERR_INVALID_REQUEST, "Query parameter %r must be one of %s." % (name, list(allowed)))
    return raw


def query_str(name, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    return raw


def query_int(name, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        fail(ERR_INVALID_REQUEST, "Query parameter %r must be an integer." % name)


def pagination_params():
    """limit/offset with the defaults, minimum and maximum of PRD section 2.3."""
    from envelope import (
        PAGINATION_DEFAULT_LIMIT,
        PAGINATION_DEFAULT_OFFSET,
        PAGINATION_MAX_LIMIT,
        PAGINATION_MIN_LIMIT,
    )

    limit = query_int("limit", PAGINATION_DEFAULT_LIMIT)
    offset = query_int("offset", PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT:
        fail(ERR_INVALID_REQUEST, "limit must be at least %d." % PAGINATION_MIN_LIMIT)
    if limit > PAGINATION_MAX_LIMIT:
        fail(ERR_INVALID_REQUEST, "limit must be at most %d." % PAGINATION_MAX_LIMIT)
    if offset < 0:
        fail(ERR_INVALID_REQUEST, "offset must not be negative.")
    return limit, offset


def ordered_by_creation(rows):
    """Default list order: creation timestamp ascending (PRD section 2.3)."""
    import db

    return sorted(rows, key=lambda r: (r.get("created_at"), db.creation_seq(r)))


def query_variant(name, allowed):
    """plan_variant / earnings_variant; values are accepted case-insensitively."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    upper = raw.upper()
    if upper in allowed:
        return upper
    fail(ERR_INVALID_REQUEST, "Query parameter %r must be one of %s." % (name, list(allowed)))