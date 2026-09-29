"""Response envelope, pagination and request-context helpers (PRD 2.1-2.3)."""
import random
import string

from flask import g, jsonify, request

from constants import (ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE,
                       LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT,
                       OFFSET_MIN)
from db import iso, wall_now
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(wall_now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


# --- authentication / authorization ----------------------------------------

def authenticate(allowed_roles):
    """Ladder rungs 1 and 2 of PRD 2.8."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def actor():
    return g.user_id


# --- pagination -------------------------------------------------------------

def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if (negative or text.startswith("+")) else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' is out of range." % name)
    return value


def pagination():
    """Rung 4: limit/offset bounds are rejected, never clamped (PRD 2.3)."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def filter_param(name, allowed=None):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if allowed is not None and value not in allowed:
        # An unrecognised enum filter value simply matches nothing.
        return "\x00__no_match__"
    return value


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
