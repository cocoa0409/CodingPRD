"""Request helpers: auth, role gating, pagination, payload well-formedness."""

from flask import request

import envelope
from errors import ApiError

ROLES = ("Anonymous", "Member", "HostOperator", "PlatformAdmin")


def principal():
    """Extract and validate the acting identity from the two mandatory headers."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    role = role.strip()
    user_id = user_id.strip()
    if role not in ROLES or not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    return {"role": role, "id": user_id}


def authorize(actor, allowed):
    """Reject the caller unless its role is permitted for the operation."""
    if actor["role"] not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require_host_scope(actor, host_id):
    """A HostOperator may only operate on its own HostBusiness (PRD 2.1)."""
    if actor["role"] == "HostOperator" and actor["id"] != host_id:
        raise ApiError("ERR_UNAUTHORIZED", "The acting host operator does not own this host.")


def require_member_scope(actor, member_id):
    """A Member may only operate on its own records (PRD 2.1)."""
    if actor["role"] == "Member" and actor["id"] != member_id:
        raise ApiError("ERR_UNAUTHORIZED", "The acting member does not own this resource.")


def json_body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def item_int(value, name):
    """Strict integer from a query parameter (no silent truncation)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def date_param(value, name):
    """A day boundary supplied as an instant; midnight UTC when only a day is given."""
    if value is None:
        return None
    if isinstance(value, str) and "T" not in value and ":" not in value:
        value = value.strip() + "T00:00:00Z"
    try:
        return envelope.parse_iso(value)
    except ApiError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % name)


def _pad_day(text):
    """Tolerate an unpadded day component such as '2026-06-5'."""
    parts = text.strip().split("-")
    if len(parts) == 3:
        parts[2] = parts[2].zfill(2)
        return "-".join(parts)
    return text


def date_param(value, name):
    """A day boundary supplied as an instant; midnight UTC when only a day is given."""
    if value is None:
        return None
    if isinstance(value, str) and "T" not in value and ":" not in value:
        value = _pad_day(value) + "T00:00:00Z"
    try:
        return envelope.parse_iso(value)
    except ApiError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % name)


def arrival_param(value):
    """arrival_date is declared as a day: anything inside the first 24 hours is
    normalized to midnight UTC."""
    if isinstance(value, str) and "T" not in value and ":" not in value:
        instant = date_param(value, "arrival_date")
    else:
        instant = date_param(value, "arrival_date")
    return instant.replace(hour=0, minute=0, second=0, microsecond=0)


def query(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


# --- payload field helpers -------------------------------------------------

def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    return body[field]


def text_field(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return value.strip()


def enum_field(body, field, allowed, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value.strip() not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field %s must be one of %s." % (field, ", ".join(allowed)),
        )
    return value.strip()


def require_fields(body, names):
    """Every named field must be present and non-null, or the payload is malformed."""
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % name)


def optional_fields(body, names):
    """The declared version precondition: rejected if present though undeclared."""
    for name in names:
        if name in body and body[name] is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field %s is not accepted by this operation." % name,
            )


def int_field(body, field, required=False, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is below its minimum." % field)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is above its maximum." % field)
    return value


def bool_field(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return value


# --- query helpers ---------------------------------------------------------

def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0); malformed -> 400."""
    raw_limit = query("limit")
    raw_offset = query("offset")
    if raw_limit is None:
        limit = 10
    else:
        limit = item_int(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is None:
        offset = 0
    else:
        offset = item_int(raw_offset, "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def bool_query(name):
    raw = query(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def page(items, limit, offset):
    return items[offset: offset + limit], len(items)