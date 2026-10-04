"""Auth header extraction, role checking and payload reading."""

from functools import wraps

from flask import request

from errors import ROLES, fail

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


def acting_context():
    role = request.headers.get(ROLE_HEADER)
    identity = request.headers.get(ID_HEADER)
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return role, identity


def auth(allowed_roles):
    """Validate the declared role headers, then the endpoint's permitted roles."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, identity = acting_context()
            if role not in allowed_roles:
                fail("ERR_FORBIDDEN")
            request.acting_role = role
            request.acting_identity = identity
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def body(required=(), optional=(), defaults=None):
    """Read the JSON body, enforcing required fields.

    Fields the API computes itself are ignored rather than rejected, so a
    client that echoes a derived field back cannot corrupt it.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST")
    out = {}
    if defaults:
        out.update(defaults)
    for field in required:
        if field not in payload or payload[field] is None:
            fail("ERR_INVALID_REQUEST")
        out[field] = payload[field]
    for field in optional:
        if field in payload and payload[field] is not None:
            out[field] = payload[field]
    return out


def enum_value(value, allowed, field=None):
    if value not in allowed:
        fail("ERR_INVALID_REQUEST")
    return value


def positive_int(value, field, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST")
    if allow_zero:
        if value < 0:
            fail("ERR_INVALID_REQUEST")
    elif value <= 0:
        fail("ERR_INVALID_REQUEST")
    return value


def non_negative_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST")
    if value < 0:
        fail("ERR_INVALID_REQUEST")
    return value


def string_value(value, field, allow_empty=False):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST")
    if not allow_empty and value == "":
        fail("ERR_INVALID_REQUEST")
    return value


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def pagination_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail("ERR_INVALID_REQUEST")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST")
        if offset < 0:
            fail("ERR_INVALID_REQUEST")
    return limit, offset


def paginated(records, serialize):
    limit, offset = pagination_args()
    total_count = len(records)
    window = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(window) < total_count,
    }
    return [serialize(r) for r in window], meta