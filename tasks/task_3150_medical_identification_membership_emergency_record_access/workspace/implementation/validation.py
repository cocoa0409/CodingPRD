"""Auth + validation helpers per PRD §2.1 and §2.5."""

from flask import request

import db
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MEMBER_NOT_FOUND,
    ERR_GUARDIANSHIP_REQUIRED,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)

ALL_ROLES = [
    "Member",
    "Guardian",
    "RecordVerifier",
    "Responder",
    "HotlineOperator",
    "FulfillmentAgent",
    "PlatformAdmin",
]


def actor():
    """Priority 1: auth header presence. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid == "" or role == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid, role


def require_roles(role, allowed):
    """Priority 2: role authorization."""
    if role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this endpoint",
        )


def get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "memberId does not exist")
    return m


def check_member_scope(uid, role, member_id):
    """Priority 4: Guardian scoping / Member self-service.

    Guardian acting on dependent's resource must hold ACTIVE GuardianLink with
    guardian_member_id == X-User-ID and member_id == path memberId.
    Member role may act only on own record (X-User-ID == memberId).
    """
    if role == "Member":
        if uid != member_id:
            raise ApiError(
                ERR_GUARDIANSHIP_REQUIRED,
                "A Member may act only on their own record",
            )
    elif role == "Guardian":
        ok = any(
            gl
            for gl in db.guardian_links.values()
            if gl["status"] == "ACTIVE"
            and gl["guardian_member_id"] == uid
            and gl["member_id"] == member_id
        )
        if not ok:
            raise ApiError(
                ERR_GUARDIANSHIP_REQUIRED,
                "Guardian lacks an ACTIVE GuardianLink to the path member",
            )
    # Other roles (PlatformAdmin, HotlineOperator, etc.) are not scoped here.


def require_member_active(member):
    """Priority 5: member lifecycle gating for writes."""
    if member["status"] != "ACTIVE":
        raise ApiError(
            ERR_MEMBER_NOT_ACTIVE, "Operation requires Member.status == ACTIVE"
        )


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"Invalid value for {field}: {v}")
    return v


def require_occ(body, member):
    """Priority 16 / §2.8: OCC check for order-confirm and record-supersede."""
    if "expected_member_version" not in body or body["expected_member_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: expected_member_version")
    ev = body["expected_member_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_member_version must be an integer")
    if ev != member["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_member_version does not match Member.version",
        )


def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, "limit out of range (1..100)")
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    """items sorted by created_at ascending (callers sort before passing)."""
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    return page, total, has_more
