"""Auth header extraction and role checking.

PRD §2.1: every credentialed request carries `X-User-ID` and `X-User-Role`.
The only role whose X-User-ID identifies a persisted row is `Seller`, and the
match is made against the `Seller` entity's `id`.
"""

from flask import request

from db import store
from errors import fail
from vocab import ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# The two endpoints that admit no credentials at all.
CREDENTIAL_FREE = {
    ("POST", "/v1/sellers"),
    ("POST", "/v1/trade-ins"),
}


class Principal:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Principal(%r, %r)" % (self.role, self.user_id)


def authenticate(method, path, credentials_optional=False):
    """Priority 1: the credential check.

    Returns a Principal, or raises ERR_UNAUTHENTICATED.
    """
    if credentials_optional or (method, path) in CREDENTIAL_FREE:
        role = request.headers.get(USER_ROLE_HEADER) or "Anonymous"
        user_id = request.headers.get(USER_ID_HEADER) or "anonymous"
        return Principal(role, user_id)

    role = request.headers.get(USER_ROLE_HEADER)
    user_id = request.headers.get(USER_ID_HEADER)
    if not role or role not in ROLES:
        raise fail("ERR_UNAUTHENTICATED")
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise fail("ERR_UNAUTHENTICATED")
    return Principal(role, user_id)


def require_role(principal, allowed):
    """Priority 3: the role check against the endpoint's authorised set.

    For the entity-backed `Seller` role the X-User-ID must additionally
    identify an existing Seller row.
    """
    if principal.role not in allowed:
        raise fail("ERR_FORBIDDEN_ROLE")
    if principal.role == "Seller" and principal.user_id not in store.sellers:
        raise fail("ERR_FORBIDDEN_ROLE")


def ensure_owner(principal, seller_id):
    """Ownership check for scoped Seller resources (PRD §2.1)."""
    if principal.role == "Seller" and principal.user_id != seller_id:
        raise fail("ERR_FORBIDDEN_ROLE")