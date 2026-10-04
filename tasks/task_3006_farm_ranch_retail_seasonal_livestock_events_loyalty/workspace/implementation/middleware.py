"""Auth helpers per PRD §2.1 / §2.9 validation order.

Role hierarchy: RegionalAdmin > StoreManager > StoreAssociate. Each level can
perform every operation of the levels below it, plus its own exclusive ops.
Customer identity is entity-backed: X-User-ID must equal the LoyaltyAccount id
of the resource being created/acted upon.
"""

from flask import request

import errors

ROLES = {"RegionalAdmin", "StoreManager", "StoreAssociate", "Customer", "Anonymous"}

_HIERARCHY = {
    "RegionalAdmin": {"RegionalAdmin", "StoreManager", "StoreAssociate"},
    "StoreManager": {"StoreManager", "StoreAssociate"},
    "StoreAssociate": {"StoreAssociate"},
    "Customer": {"Customer"},
    "Anonymous": {"Anonymous"},
}


def user_context():
    """Return (user_id, role); raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise errors.err_missing_user_context()
    return uid, role


def check_role(role, allowed):
    """allowed is a collection of base role names permitted for the endpoint."""
    granted = _HIERARCHY[role]
    if not (granted & set(allowed)):
        raise errors.err_forbidden_role()


def check_identity(uid, role, account_id):
    """Entity-backed identity check (priority 3) for Customer actors."""
    if role == "Customer" and uid != account_id:
        raise errors.err_forbidden_identity()


def get_json():
    """Return the request JSON object ({} when absent); non-object payloads are invalid."""
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err_invalid_request("JSON body must be an object")
    return data


def parse_pagination(args):
    """limit/offset per PRD §2.3: defaults 10/0, limit in [1, 100]."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise errors.err_invalid_request("limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise errors.err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.err_invalid_request("limit out of range [1, 100]")
    if offset < 0:
        raise errors.err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable) and window."""
    items = sorted(items, key=lambda r: r.get("created_at"))
    total = len(items)
    return items[offset:offset + limit], total
