"""Auth middleware: X-User-ID / X-User-Role extraction, role checking, pagination."""

from flask import request

from errors import err_unauthenticated, err_unauthorized_role, err_invalid_request

ROLES = {
    "PlatformAdmin",
    "DataAcquisitionManager",
    "PrivacyOfficer",
    "SupplierOperator",
    "ManufacturerClient",
}

ALL_ROLES = [
    "PlatformAdmin",
    "DataAcquisitionManager",
    "PrivacyOfficer",
    "SupplierOperator",
    "ManufacturerClient",
]


def get_auth():
    """Validate the auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_role(allowed):
    """Validate auth headers and endpoint role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized_role()
    return user_id, role


def get_pagination():
    """Parse limit/offset query params with PRD section 2.3 defaults/bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset
