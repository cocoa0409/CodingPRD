"""Identity, roles and the separation of duties (PRD 2.1, validations 1-3)."""

import functools

from flask import request

from errors import ApiError

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_AGENCY_REP = "AgencyRep"
ROLE_DEV_EXEC = "DevelopmentExec"
ROLE_BUSINESS_AFFAIRS = "BusinessAffairs"
ROLE_FINANCE = "FinanceController"
ROLE_RESEARCH = "ResearchAnalyst"
ROLE_STUDIO = "StudioPartner"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_AGENCY_REP,
    ROLE_DEV_EXEC,
    ROLE_BUSINESS_AFFAIRS,
    ROLE_FINANCE,
    ROLE_RESEARCH,
    ROLE_STUDIO,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# committee -> the single role permitted to cast it (PRD 2.1, validation 4)
COMMITTEE_ROLE = {
    "CREATIVE": ROLE_DEV_EXEC,
    "BUSINESS": ROLE_BUSINESS_AFFAIRS,
    "FINANCE": ROLE_FINANCE,
}


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_agency_rep(self):
        return self.role == ROLE_AGENCY_REP


def current_principal():
    """Validation 1 then validation 2 (role membership only)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED")
    return Principal(user_id, role)


def authorize(*allowed_roles):
    """Decorator enforcing validations 1 and 2 for one endpoint."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            principal = current_principal()
            if principal.role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED")
            return view(principal, *args, **kwargs)

        return wrapper

    return decorator


def agency_scope_guard(principal, agency_id):
    """Validation 3 -- an AgencyRep may only touch their own agency."""
    if not principal.is_agency_rep:
        return
    if agency_id is None or agency_id != principal.user_id:
        raise ApiError("ERR_AGENCY_SCOPE_VIOLATION")
