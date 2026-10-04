"""Auth and request helpers per PRD §2.1 / §2.6 validation order.

Auth headers: X-User-Role (always) and X-User-ID (required for the
entity-backed roles Customer, Picker, Driver; opaque for SiteOps).
"""

from flask import request

import errors

ROLES = {"Customer", "Picker", "Driver", "SiteOps"}
ENTITY_BACKED = {"Customer", "Picker", "Driver"}


def user_context():
    """Return (user_id, role); raises ERR_UNAUTHENTICATED on missing/malformed."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise errors.err_unauthenticated()
    if role in ENTITY_BACKED and not uid:
        raise errors.err_unauthenticated()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise errors.err_unauthorized("Role not permitted for this endpoint")


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
    items = sorted(items, key=lambda r: (r.get("created_at"), r.get("id")))
    total = len(items)
    return items[offset:offset + limit], total
