"""Auth middleware: X-User-ID / X-User-Role extraction and RBAC enforcement."""

from flask import request

from errors import unauthenticated, unauthorized

ROLES = {
    "ClubAdmin",
    "MemberServicesRep",
    "Dispatcher",
    "ProviderOps",
    "SettlementClerk",
    "FederationFinance",
    "Agent",
}


def require_auth(allowed_roles):
    """Validate auth headers and role permission. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    if allowed_roles is not None and role not in allowed_roles:
        raise unauthorized()
    return user_id, role


def get_pagination():
    """Parse limit/offset with defaults from the response envelope spec.

    Invalid values (non-integer) are rejected with 400 via ApiError.
    Out-of-range values are clamped to [1,100] for limit and >=0 for offset.
    """
    from errors import invalid_request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset
