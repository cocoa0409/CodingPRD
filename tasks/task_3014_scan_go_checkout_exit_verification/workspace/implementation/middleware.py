"""Auth header extraction, role checking, and shared helpers."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_RESOURCE_OWNERSHIP,
    ERR_INVALID_REQUEST,
)

ROLES = {"Member", "Associate", "LossPreventionOfficer", "ClubManager", "PlatformAdmin"}

ALL_ROLES = ["Member", "Associate", "LossPreventionOfficer", "ClubManager", "PlatformAdmin"]


def get_context():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role.",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Role not permitted for this endpoint.",
            403,
        )


def check_ownership(user_id, owner_member_id):
    if user_id != owner_member_id:
        raise ApiError(
            ERR_FORBIDDEN_RESOURCE_OWNERSHIP,
            "Member-scoped action attempted on another member's resource.",
            403,
        )


def get_body():
    """Parse JSON body; tolerate empty bodies on POST action endpoints."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def get_pagination(args):
    """Parse limit/offset query params with defaults limit=10, offset=0 (min 1, max 100)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer.", 400)
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer.", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100.", 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0.", 400)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
