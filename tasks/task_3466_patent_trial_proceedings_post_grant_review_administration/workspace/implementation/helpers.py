"""Response envelope, pagination, auth/role checks, and request validation
helpers. All structural names are taken from SCAFFOLD.yaml section 1.0 and
PRD section 2."""

import random
import string

from flask import jsonify, request

from db import store, strip_internal
from errors import (
    ApiError,
    raise_err,
    ERR_MISSING_AUTH_HEADERS,
    ERR_FORBIDDEN_ROLE,
    ERR_VALIDATION,
)

ALL_ROLES = ["PlatformAdmin", "BoardPanel", "Petitioner", "PatentOwner", "AppealsCourt"]


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        # PRD 2.4: every system-generated timestamp reads the logical clock.
        "api_request_timestamp": store.clock.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(entities):
    """Sort by created_at ascending (insertion order tie-break) and apply
    limit/offset per PRD 2.3 (default 10, min 1, max 100, offset default 0)."""
    ordered = sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be an integer between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            raise_err(ERR_VALIDATION, "offset must be a non-negative integer")
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return [strip_internal(e) for e in page], pagination


def list_response(entities):
    items, pagination = paginate(entities)
    return success_list(items, pagination)


# ---------------------------------------------------------------------------
# Auth (validation priorities 1 and 2)
# ---------------------------------------------------------------------------

def auth_headers():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise_err(ERR_MISSING_AUTH_HEADERS,
                  "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_roles(*roles):
    user_id, role = auth_headers()
    if role not in ALL_ROLES or role not in roles:
        raise_err(ERR_FORBIDDEN_ROLE,
                  f"role {role!r} may not call this endpoint")
    return user_id, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Field validators (priority 5 — ERR_VALIDATION)
# ---------------------------------------------------------------------------

def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_string(body, field, allow_empty=False):
    value = body.get(field)
    if not isinstance(value, str) or (not allow_empty and value.strip() == ""):
        raise_err(ERR_VALIDATION, f"{field} must be a non-empty string")
    return value


def opt_string(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"{field} must be a string")
    return value


def req_int(body, field, minimum=None):
    value = body.get(field)
    if not is_int(value):
        raise_err(ERR_VALIDATION, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_VALIDATION, f"{field} must be >= {minimum}")
    return value


def opt_int(body, field, minimum=None):
    if field not in body or body.get(field) is None:
        return None
    return req_int(body, field, minimum)


def req_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        raise_err(ERR_VALIDATION, f"{field} must be one of {sorted(allowed)}")
    return value


def req_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        raise_err(ERR_VALIDATION, f"{field} must be a boolean")
    return value


def req_array(body, field, non_empty=True):
    value = body.get(field)
    if not isinstance(value, list) or (non_empty and len(value) == 0):
        raise_err(ERR_VALIDATION, f"{field} must be a non-empty array")
    return value


def request_arg(name):
    """Optional query-string filter value; empty string counts as absent."""
    value = request.args.get(name)
    return value if value not in (None, "") else None
