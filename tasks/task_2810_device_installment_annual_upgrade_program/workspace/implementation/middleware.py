"""Authentication, authorization and Customer ownership screens (PRD 2.1, 2.7)."""
from flask import g, request

from constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE, ROLE_CUSTOMER
from errors import ApiError


def authenticate():
    """Band 1 of the ladder: both headers present, non-empty, role declared."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Band 2a: the endpoint's own authorization list."""
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")


def require_owner(customer_id):
    """Band 2b: a Customer may only reach records they own.

    ``customer_id`` may be None when the owning record could not be resolved --
    the later existence band reports that case.
    """
    if g.role != ROLE_CUSTOMER:
        return
    if customer_id is None:
        return
    if customer_id != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED")


def is_customer():
    return g.role == ROLE_CUSTOMER
