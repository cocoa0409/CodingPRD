"""Auth header extraction, role checking, and pagination helpers."""
from __future__ import annotations

from flask import request

from errors import forbidden, unauthenticated, invalid_request

VALID_ROLES = {
    "PlatformAdmin",
    "OrganizationAdmin",
    "BillingContact",
    "TrustAnalyst",
    "TrustLead",
}


def current_user():
    """Extract and validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in VALID_ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(*roles: str):
    user_id, role = current_user()
    if role not in roles:
        raise forbidden()
    return user_id, role


def pagination_params():
    """Parse limit/offset query params with defaults; errors -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit out of range [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, dict]:
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
