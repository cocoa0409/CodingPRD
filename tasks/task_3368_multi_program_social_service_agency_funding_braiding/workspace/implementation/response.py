"""Response envelope, pagination and request-level auth helpers."""

import random
import string

from flask import request

import clock
from errors import ApiError

ROLES = [
    "IntakeSpecialist",
    "ProgramManager",
    "FinanceOfficer",
    "ComplianceOfficer",
    "Client",
    "PlatformAdmin",
]

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0

_ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(16))


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def object_envelope(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def array_envelope(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return {"meta": meta, "response_type": "array", "data": rows}


def error_envelope(error):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }


def auth_context():
    """Priority 1: both headers present and the role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be declared.",
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2: the acting role must appear in the endpoint's roles set."""
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorized for this operation." % role,
        )


def pagination_args():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else PAGINATION_LIMIT_DEFAULT
    except (TypeError, ValueError):
        limit = PAGINATION_LIMIT_DEFAULT
    try:
        offset = int(offset_raw) if offset_raw is not None else PAGINATION_OFFSET_DEFAULT
    except (TypeError, ValueError):
        offset = PAGINATION_OFFSET_DEFAULT
    limit = max(PAGINATION_LIMIT_MIN, min(PAGINATION_LIMIT_MAX, limit))
    offset = max(0, offset)
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def require_fields(data, names):
    missing = [n for n in names if data.get(n) is None]
    if missing:
        raise ApiError(
            "ERR_BAD_REQUEST",
            "Missing required field(s): %s" % ", ".join(missing),
        )


def money(value):
    """Integer cents from a JSON number/string; never a float dollar figure."""
    if value is None:
        return None
    return int(value)
