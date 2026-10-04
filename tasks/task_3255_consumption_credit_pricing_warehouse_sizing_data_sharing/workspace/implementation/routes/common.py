"""Shared request-body helpers."""
from flask import g, request

from errors import err
from util import num, as_int

MISSING = object()


def require_provider_ownership(provider_account_id):
    """PRD §2.1: when `X-User-Role` is `ShareAdmin`, `X-User-ID` is the `id` of
    the acting `Account`, and ownership checks on any resource that references an
    `Account` compare that resource's foreign-key field to it. A ShareAdmin
    acting against another provider's account is not authorized for that
    operation and is refused with `ERR_FORBIDDEN_ROLE`."""
    if g.role == "ShareAdmin" and g.user_id != provider_account_id:
        raise err("ERR_FORBIDDEN_ROLE",
                  "The acting ShareAdmin does not own this resource's account.")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def required(data, field):
    if field not in data or data[field] is None:
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    return data[field]


def opt(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return data[field]


def opt_bool(data, field, default):
    value = opt(data, field, MISSING)
    if value is MISSING:
        return default
    if isinstance(value, bool):
        return value
    raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)


def opt_int(data, field, default):
    value = opt(data, field, MISSING)
    if value is MISSING:
        return default
    try:
        return as_int(value, field)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)


def opt_dec(data, field, default):
    value = opt(data, field, MISSING)
    if value is MISSING:
        return default
    try:
        return num(value, field)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)


def req_dec(data, field):
    value = required(data, field)
    try:
        return num(value, field)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)


def req_int(data, field):
    value = required(data, field)
    try:
        return as_int(value, field)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)


def req_str(data, field):
    value = required(data, field)
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default):
    value = opt(data, field, MISSING)
    if value is MISSING:
        return default
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_iso(data, field, default):
    from util import parse_iso
    value = opt(data, field, MISSING)
    if value is MISSING:
        return default
    try:
        return parse_iso(value, field)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % field)


def req_iso(data, field):
    from util import parse_iso
    value = required(data, field)
    try:
        return parse_iso(value, field)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % field)
