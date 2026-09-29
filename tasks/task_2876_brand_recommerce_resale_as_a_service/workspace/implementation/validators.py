"""Header guards, body-shape validation and query-parameter parsing.

The helpers here implement steps 1 to 3 of the admission order in PRD 2.11:
authentication, authorization and body shape, in that order.
"""

from flask import request

import store
from errors import ApiError


def guard(*allowed_roles):
    """Authenticate, then authorize.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role") or ""
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role '%s' may not call this endpoint." % (role or "<missing>"),
        )
    return user_id, role


def body():
    """The JSON body as a dict.  A body that is absent is an empty object."""
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def _missing(name):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def has(payload, name):
    return name in payload and payload[name] is not None


def str_field(payload, name, required=True, default=None, allow_blank=False):
    if not has(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_blank and value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def enum_field(payload, name, allowed, required=True, default=None):
    if not has(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def int_field(payload, name, required=True, default=None, minimum=0, maximum=None):
    if not has(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def ts_field(payload, name, required=True, default=None):
    if not has(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    parsed = store.parse_ts(value)
    if parsed is None:
        _bad(name, "must be a valid ISO 8601 UTC instant")
    return parsed


def id_field(payload, name, required=True, default=None):
    if not has(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty identifier string")
    return value


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def _int_query(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be at least %d." % (name, minimum),
        )
    if maximum is not None and value > maximum:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be at most %d." % (name, maximum),
        )
    return value


def pagination():
    limit = _int_query("limit", 10, 1, 100)
    offset = _int_query("offset", 0, 0, None)
    return limit, offset


def enum_query(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return raw


def id_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def unique_or_reject(table_name, field, value, scope=None):
    """Reject a duplicate value; there is no dedicated catalogue code for it."""
    for row in store.rows(table_name):
        if scope is not None and row.get(scope[0]) != scope[1]:
            continue
        if row.get(field) == value:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be unique; '%s' is already in use." % (field, value),
            )
