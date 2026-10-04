"""Auth header extraction, role gating, agency scope, body and pagination
helpers. Header names are exactly X-User-ID / X-User-Role (PRD section 2.1).
"""
import math

from flask import request

from errors import ApiError

ALL_ROLES = ["GSAAdmin", "GSALeasingOfficer", "GSAPropertyManager", "AgencyManager", "LessorRep"]


def require_auth(allowed_roles):
    """Priority 1: headers present and non-empty. Priority 2: role allowed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid.strip() == "" or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    role = role.strip()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Caller's role is not authorized for this endpoint")
    return uid.strip(), role


def agency_scope(uid, role, agency_id):
    """Priority 3: an AgencyManager's X-User-ID must equal the target
    resource's agency_id. Other roles carry opaque identity (no check)."""
    if role == "AgencyManager" and uid != agency_id:
        raise ApiError(
            "ERR_AGENCY_SCOPE_VIOLATION",
            403,
            "AgencyManager may only act on resources of their own agency",
        )


def body():
    """Request JSON body as a dict; missing/malformed body reads as {}."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def paginate(items):
    """limit/offset per PRD section 2.3: default 10/0, limit within 1..100."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit, offset = 10, 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
