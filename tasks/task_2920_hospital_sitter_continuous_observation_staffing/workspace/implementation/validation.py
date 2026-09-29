"""Rung 1-3 of the enforcement ladder: authentication, role authorization and
request-shape validation (PRD 2.1, 2.3, 2.6)."""
from flask import request

from db import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    ROLES,
    parse_instant,
)
from errors import fail


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Rung 1 then rung 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not role.strip():
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_ROLE_NOT_PERMITTED", "Unrecognized role '%s'." % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
    return Caller(user_id, role)


# ---------------------------------------------------------------------------
# Body shape helpers (rung 3). Every failure is ERR_INVALID_REQUEST / 400.
# ---------------------------------------------------------------------------
def body_json():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, min_len=1, max_len=None):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %d characters." % (field, max_len))
    return value


def opt_str(body, field, min_len=1, max_len=None, default=None):
    if not _present(body, field):
        return default
    return req_str(body, field, min_len, max_len)


def raw_opt_str(body, field, default=None):
    """A string field with no length constraint declared in the PRD."""
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return value


def req_int(body, field, lo=None, hi=None):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = body[field]
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (field, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (field, hi))
    return value


def opt_int(body, field, lo=None, hi=None, default=None):
    if not _present(body, field):
        return default
    return req_int(body, field, lo, hi)


def req_bool(body, field):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def opt_bool(body, field, default=None):
    if not _present(body, field):
        return default
    return req_bool(body, field)


def req_enum(body, field, members):
    value = req_str(body, field, 1, None)
    if value not in members:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def opt_enum(body, field, members, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, members)


def req_instant(body, field):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = body[field]
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a parseable ISO-8601 instant." % field)
    return parsed


def req_enum_array(body, field, members, non_empty=True, unique=True):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % field)
    for item in value:
        if not isinstance(item, str) or item not in members:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' members must be drawn from %s." % (field, ", ".join(members)))
    if unique and len(set(value)) != len(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must not contain duplicates." % field)
    return list(value)


def req_str_array(body, field, non_empty=False):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % field)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' members must be strings." % field)
    return list(value)


# ---------------------------------------------------------------------------
# Query string helpers.
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST",
                 "Query parameter 'limit' must be between %d and %d."
                 % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def enum_filter(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return raw


def plain_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
