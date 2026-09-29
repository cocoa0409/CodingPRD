"""Authentication, role authorisation and ownership (PRD 2.7).

Ladder positions 1 (ERR_UNAUTHENTICATED), 2 (ERR_ROLE_NOT_PERMITTED) and
6 (ERR_NOT_RESOURCE_OWNER).
"""

import functools

from flask import g, request

from constants import ROLES
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def authenticate():
    """Both headers must be present and the role must be one of the six."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "role", None)


def require_roles(*allowed):
    """Reject an unauthorised-but-authenticated role before anything else."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if current_role() not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            return fn(*args, **kwargs)

        wrapper._allowed_roles = allowed
        return wrapper

    return decorator


def require_seller_owner(seller_id):
    """A SellerRep's X-User-ID is the id of the acting Seller."""
    if current_role() == "SellerRep" and current_user_id() != seller_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_advertiser_owner(advertiser_id):
    """An AdvertiserClient's X-User-ID is the id of the acting Advertiser."""
    if current_role() == "AdvertiserClient" and current_user_id() != advertiser_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
