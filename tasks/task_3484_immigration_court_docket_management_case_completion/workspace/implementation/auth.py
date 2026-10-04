# auth.py — PRD §2.1 user context (tier 1) and endpoint permission (tier 2).
from flask import request

import db
from constants import (ROLES, ROLE_IMMIGRATION_JUDGE, HEADER_USER_ID,
                       HEADER_USER_ROLE)
from errors import ApiError


def get_auth():
    """Tier 1: both headers present, role is one of the three declared values,
    and an ImmigrationJudge caller's X-User-ID resolves to an existing Judge."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role "
            "must be one of CourtAdministrator, ImmigrationJudge, BoardMember")
    if role == ROLE_IMMIGRATION_JUDGE and user_id not in db.judges:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID must be the id of an existing Judge when the role "
            "is ImmigrationJudge")
    return user_id, role


def require_role(role, allowed):
    """Tier 2: the declared role must be permitted on this endpoint."""
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s is not permitted on this endpoint" % role)


ALL_ROLES = ROLES
