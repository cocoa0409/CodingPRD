"""Authentication and authorisation (PRD §2.1, SCAFFOLD.yaml §1.4 priority 1-2).

Header names are the ones the auth validation names literally: `X-User-Role`
and `X-User-ID`.  The three recognised roles are `PlatformAdmin`,
`StoreAssociate` and `Member`.
"""

from flask import request

from errors import fail

VALID_ROLES = ("PlatformAdmin", "StoreAssociate", "Member")


def principal():
    """Return (role, user_id) after the authentication rung.

    A missing header, or a role outside the recognised set, is refused with
    ERR_UNAUTHENTICATED before any resource is resolved.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in VALID_ROLES:
        fail("ERR_UNAUTHENTICATED",
             "X-User-Role and X-User-ID headers are required and the role must "
             "be one of PlatformAdmin, StoreAssociate, Member.")
    return role, user_id


def require(*roles):
    """Return (role, user_id), refusing roles not permitted for the operation."""
    role, user_id = principal()
    if roles and role not in roles:
        fail("ERR_FORBIDDEN",
             "The acting role is not permitted to perform this operation.")
    return role, user_id


def require_owner(member_id):
    """Return (role, user_id) and enforce the member ownership rung.

    Ownership is checked only when the caller is acting as a Member; the
    operator roles identify themselves opaquely and are not matched against
    any entity id.
    """
    role, user_id = principal()
    if role == "Member" and member_id is not None and user_id != member_id:
        fail("ERR_FORBIDDEN",
             "A member may only act on a row they own.")
    return role, user_id


def is_member_caller():
    return request.headers.get("X-User-Role") == "Member"