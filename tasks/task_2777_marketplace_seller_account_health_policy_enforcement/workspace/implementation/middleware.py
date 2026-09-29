"""Authentication, role authorisation, ownership and segregation of duties."""

from functools import wraps

from flask import g, request

import constants as C
from errors import ApiError


def require(*roles):
    """PRD 2.8 steps 1 and 2: authenticate, then authorise the acting role."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            role = request.headers.get(C.HEADER_ROLE)
            if role is None or role not in C.ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            user_id = request.headers.get(C.HEADER_USER)
            if role != C.ROLE_ANONYMOUS and (user_id is None or user_id == ""):
                raise ApiError("ERR_UNAUTHENTICATED")
            g.role = role
            g.user_id = None if role == C.ROLE_ANONYMOUS else user_id
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def role():
    return getattr(g, "role", None)


def actor():
    return getattr(g, "user_id", None)


def is_seller():
    return role() == C.ROLE_SELLER


def ensure_owner(seller_id):
    """PRD 2.8 step 5 — only ever applied to a Seller caller."""
    if is_seller() and actor() != seller_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def ensure_distinct(*conflicting_user_ids):
    """PRD 2.7 — compares X-User-ID against the earlier step's recorded user."""
    for other in conflicting_user_ids:
        if other is not None and actor() == other:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
