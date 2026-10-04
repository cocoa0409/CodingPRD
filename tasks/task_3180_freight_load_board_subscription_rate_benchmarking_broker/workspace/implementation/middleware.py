from flask import request

from response import APIError
from util import ROLES


def get_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise APIError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and must be well-formed",
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise APIError(
            "ERR_UNAUTHORIZED_ROLE", 403, f"Role {role} is not permitted for this endpoint"
        )
