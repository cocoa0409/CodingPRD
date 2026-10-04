"""Auth, body parsing, and field validation helpers.

Implements PRD section 2.5 priorities 1-3 (authentication, role authorization,
request schema) plus shared input parsers used by the route modules.
"""
from datetime import datetime, timezone

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_INVALID_REQUEST,
)


def _bad(msg):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def require_auth():
    """Priority 1: X-User-ID and X-User-Role present and non-blank."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip() or role is None or not str(role).strip():
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and must be non-blank.",
            401,
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2 (role part): the named role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "Role %s is not permitted to perform this operation." % role,
            403,
        )


def forbid_cross_org(actor_uid, org_id_value):
    """Priority 2 (ownership part) for entity-backed roles on create payloads.

    Only evaluated when the payload field is present and a string; a missing
    or wrongly-typed field is left for schema validation (priority 3).
    """
    if isinstance(org_id_value, str) and org_id_value != actor_uid:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "Entity-backed caller may only act on its own organization.",
            403,
        )


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise _bad("Request body must be a JSON object.")
    return body


def req_str(body, field):
    if field not in body or body[field] is None:
        raise _bad("Missing required field: %s" % field)
    value = body[field]
    if not isinstance(value, str):
        raise _bad("Field %s must be a string." % field)
    return value


def req_nonempty_str(body, field):
    value = req_str(body, field)
    if not value.strip():
        raise _bad("Field %s must be non-empty." % field)
    return value


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str):
        raise _bad("Field %s must be a string." % field)
    return value


def req_int(body, field):
    if field not in body or body[field] is None:
        raise _bad("Missing required field: %s" % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("Field %s must be an integer." % field)
    return value


def req_number(body, field):
    if field not in body or body[field] is None:
        raise _bad("Missing required field: %s" % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad("Field %s must be a number." % field)
    return value


def req_bool(body, field):
    if field not in body or body[field] is None:
        raise _bad("Missing required field: %s" % field)
    if not isinstance(body[field], bool):
        raise _bad("Field %s must be a boolean." % field)
    return body[field]


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise _bad("Field %s must be a boolean." % field)
    return body[field]


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        raise _bad("Field %s must be one of %s." % (field, sorted(allowed)))
    return value


def parse_datetime_value(value, field):
    if not isinstance(value, str):
        raise _bad("Field %s must be an ISO 8601 datetime string." % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _bad("Field %s must be an ISO 8601 datetime string." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, field):
    if field not in body or body[field] is None:
        raise _bad("Missing required field: %s" % field)
    return parse_datetime_value(body[field], field)


def opt_datetime(body, field):
    if field not in body or body[field] is None:
        return None
    return parse_datetime_value(body[field], field)


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise _bad("Query parameter %s must be an integer." % name)


def paginate(items):
    """Apply limit/offset per PRD section 2.3; returns (page, limit, offset, total)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        limit = _parse_int_param(limit_raw, "limit")
        if limit < 1 or limit > 100:
            raise _bad("Query parameter limit must be within [1, 100].")
    if offset_raw is None:
        offset = 0
    else:
        offset = _parse_int_param(offset_raw, "offset")
        if offset < 0:
            raise _bad("Query parameter offset must be >= 0.")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
