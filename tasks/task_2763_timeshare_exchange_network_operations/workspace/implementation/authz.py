"""Authentication, role permissions and ownership checks (PRD 2.1, 2.10 items 1-9)."""

from flask import request

from errors import ApiError
from store import db, ROLES


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_resort_manager(self):
        return self.role == "ResortManager"

    @property
    def is_operator(self):
        return self.role == "NetworkOperator"

    @property
    def is_analyst(self):
        return self.role == "DisputeAnalyst"


def authenticate(allowed_roles):
    """Priorities 1-3: headers present, role known, role permitted for the endpoint."""
    user_id = request.headers.get("X-User-Id")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Caller(user_id, role)


def require_acting_identity(caller):
    """Priority 5: Member and ResortManager identities are looked up."""
    if caller.is_member:
        if caller.user_id not in db.members:
            raise ApiError("ERR_ACTING_IDENTITY_NOT_FOUND")
    elif caller.is_resort_manager:
        if caller.user_id not in db.resorts:
            raise ApiError("ERR_ACTING_IDENTITY_NOT_FOUND")


def acting_member(caller):
    return db.members.get(caller.user_id)


def require_owner(caller, member_id):
    """Priority 8: a Member caller may only act on rows it owns."""
    if caller.is_member and caller.user_id != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_resort_manager(caller, resort_id):
    """Priority 9: a ResortManager caller may only act on its own resort."""
    if caller.is_resort_manager and caller.user_id != resort_id:
        raise ApiError("ERR_NOT_RESORT_MANAGER")
