"""Body-shape validation primitives (admission ladder rung 5 -> ERR_INVALID_REQUEST 422).

Every helper here raises ApiError('ERR_INVALID_REQUEST') on failure; nothing in
this module ever consults stored state, so it can be run at exactly rung 5.
"""

from flask import request

from errors import ApiError
from store import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    parse_date,
    parse_instant,
    parse_period,
)

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body leniently: absent or non-object bodies read as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _present(b, key):
    return key in b and b[key] is not None


def _require_present(b, key):
    if key not in b:
        bad("Required field '%s' is missing." % key)
    if b[key] is None:
        bad("Required field '%s' must not be null." % key)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(b, key, lo=None, hi=None):
    _require_present(b, key)
    value = b[key]
    if not is_int(value):
        bad("Field '%s' must be an integer." % key)
    if lo is not None and value < lo:
        bad("Field '%s' must be >= %s." % (key, lo))
    if hi is not None and value > hi:
        bad("Field '%s' must be <= %s." % (key, hi))
    return value


def opt_int(b, key, lo=None, hi=None, default=None):
    if not _present(b, key):
        return default
    return req_int(b, key, lo, hi)


def req_bool(b, key):
    _require_present(b, key)
    value = b[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(b, key, default=None):
    if not _present(b, key):
        return default
    return req_bool(b, key)


def req_str(b, key, min_len=None, max_len=None, non_blank=False):
    _require_present(b, key)
    value = b[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if non_blank and not value.strip():
        bad("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def opt_str(b, key, min_len=None, max_len=None, non_blank=False, default=None):
    if not _present(b, key):
        return default
    return req_str(b, key, min_len, max_len, non_blank)


def req_enum(b, key, allowed):
    _require_present(b, key)
    value = b[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def opt_enum(b, key, allowed, default=None):
    if not _present(b, key):
        return default
    return req_enum(b, key, allowed)


def req_date(b, key):
    _require_present(b, key)
    parsed = parse_date(b[key])
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return parsed


def opt_date(b, key, default=None):
    if not _present(b, key):
        return default
    return req_date(b, key)


def req_instant(b, key):
    _require_present(b, key)
    parsed = parse_instant(b[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def req_period(b, key):
    _require_present(b, key)
    parsed = parse_period(b[key])
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM month string." % key)
    return b[key].strip()


def req_str_array(b, key, allowed, min_items=1, max_items=None):
    _require_present(b, key)
    value = b[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    if len(value) < min_items:
        bad("Field '%s' must have at least %d member(s)." % (key, min_items))
    if max_items is not None and len(value) > max_items:
        bad("Field '%s' must have at most %d members." % (key, max_items))
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("Field '%s' members must be drawn from %s." % (key, sorted(allowed)))
        if item in seen:
            bad("Field '%s' members must be distinct." % key)
        seen.add(item)
    return list(value)


# ---------------------------------------------------------------------------
# Pagination (PRD s2.3)
# ---------------------------------------------------------------------------
def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < PAGINATION_DEFAULT_OFFSET:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def q(name):
    value = request.args.get(name, None)
    if value is None:
        return None
    return value
