"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

ROLES = {"RegistryAdmin", "MemberRep", "QAAuditor", "BorrowerInquirer"}


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_USER_CONTEXT."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_MISSING_USER_CONTEXT",
                  "X-User-ID and X-User-Role headers are required and the role must be declared")
    return user_id, role


def require_role(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise err("ERR_ROLE_FORBIDDEN", f"Role {role} is not permitted for this endpoint")
    return user_id, role


def require_member_active(member):
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE",
                  "Acting member is not in ACTIVE status")


def acting_member(user_id):
    """Resolve the Member behind a MemberRep identity (X-User-ID == Member.id)."""
    from db import store
    return store.members.get(user_id)
