"""Identity headers, role membership and the two ownership gates (PRD 2.1, 2.8).

Ladder rungs 1-3 run in authenticate(): header presence and role membership, then
endpoint role authorization, then entity-backed identity resolution. The ownership
gates of rungs 7 and 8 are called by the individual routes after path and body
foreign keys have been resolved, because you cannot compare against the route of a
visit that is not there.
"""
from flask import request

from errors import ApiError
from store import db

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_ACCOUNT_MANAGER = "AccountManager"
ROLE_BILLING_SPECIALIST = "BillingSpecialist"
ROLE_ROUTE_TECHNICIAN = "RouteTechnician"
ROLE_CUSTOMER_CONTACT = "CustomerContact"

ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_ACCOUNT_MANAGER,
    ROLE_BILLING_SPECIALIST,
    ROLE_ROUTE_TECHNICIAN,
    ROLE_CUSTOMER_CONTACT,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class Actor(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_technician(self):
        return self.role == ROLE_ROUTE_TECHNICIAN

    @property
    def is_contact(self):
        return self.role == ROLE_CUSTOMER_CONTACT


def authenticate(allowed_roles):
    role = request.headers.get(HEADER_USER_ROLE)
    user_id = request.headers.get(HEADER_USER_ID)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "X-User-ID and a valid X-User-Role header are required.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    # Rung 3: only the two entity-backed roles resolve; opaque operator ids never do.
    if role == ROLE_ROUTE_TECHNICIAN and user_id not in db.routes:
        raise ApiError("ERR_UNKNOWN_ACTOR_IDENTITY",
                       "X-User-ID does not resolve to a route.")
    if role == ROLE_CUSTOMER_CONTACT and user_id not in db.accounts:
        raise ApiError("ERR_UNKNOWN_ACTOR_IDENTITY",
                       "X-User-ID does not resolve to an account.")
    return Actor(role, user_id)


def require_route_owner(actor, route_id):
    """Rung 7 - ERR_ACTOR_NOT_ON_ROUTE."""
    if actor.is_technician and route_id != actor.user_id:
        raise ApiError("ERR_ACTOR_NOT_ON_ROUTE",
                       "The acting technician is not the technician of this route.")


def require_account_contact(actor, account_id):
    """Rung 8 - ERR_ACTOR_NOT_ACCOUNT_CONTACT."""
    if actor.is_contact and account_id != actor.user_id:
        raise ApiError("ERR_ACTOR_NOT_ACCOUNT_CONTACT",
                       "The acting contact does not belong to this account.")
