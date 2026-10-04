"""Auth middleware: header extraction, role checking, validation-priority helpers."""

from flask import request

from errors import ApiError, err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"PlatformAdmin", "ComplianceReviewer", "Consumer", "Recipient"}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role headers.

    Returns (user_id, role). Raises ApiError on failure.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "X-User-Role is not a declared role")
    return user_id, role


def require_role(*allowed_roles):
    """Check that the caller's role is in the allowed set."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err(ERR_UNAUTHORIZED, f"Role {role} is not permitted for this endpoint")
    return user_id, role


def parse_limit_offset(args):
    """Parse limit and offset query params with scaffold defaults."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
