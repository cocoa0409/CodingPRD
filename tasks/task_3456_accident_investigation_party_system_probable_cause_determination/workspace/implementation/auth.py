"""User-context extraction and endpoint role checks (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role naming one of the ten
declared roles, else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER. Endpoint
role mismatches are ERR_INSUFFICIENT_PERMISSIONS; ownership-scoped checks are
enforced at the call sites with their dedicated error ids.
"""

from flask import request

from constants import ROLES
from errors import api_error


def get_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise api_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and name a "
            "declared role",
        )
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise api_error(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "role %s is not permitted on this endpoint" % role,
        )


def require_iic(user_id, investigation):
    """IIC ownership scope: X-User-ID must equal investigation.iic_user_id."""
    if user_id != investigation["iic_user_id"]:
        raise api_error(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "caller is not the investigation's investigator-in-charge",
        )


def require_chairman(user_id, group):
    """GroupChairman ownership scope: X-User-ID == group.chairman_user_id."""
    if user_id != group["chairman_user_id"]:
        raise api_error(
            "ERR_CHAIRMAN_OWNERSHIP",
            "caller is not the chairman of this group",
        )
