"""Authentication, the four franchisor/franchisee roles and ownership checks
(PRD 2.1) plus the validation precedence bands of PRD 2.9."""

from flask import request

from errors import ApiError

ROLE_FDM = "FranchiseDevelopmentManager"
ROLE_BSD = "BrandStandardsDirector"
ROLE_QA = "QaInspector"
ROLE_OWNER = "Owner"

ALL_ROLES = (ROLE_FDM, ROLE_BSD, ROLE_QA, ROLE_OWNER)


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_owner(self):
        return self.role == ROLE_OWNER


def authenticate(allowed_roles):
    """Bands 1-3 of PRD 2.9: headers present, role recognised, role admitted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    if role not in ALL_ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Principal(user_id, role)


def require_owner(principal, owner_id):
    """Band 6: an Owner may only act on resources of its own ownership entity."""
    if principal.role != ROLE_OWNER:
        return
    if owner_id is None or principal.user_id != owner_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")
