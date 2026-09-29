"""Authentication, role authorisation and ownership scoping (PRD section 2.1)."""

from flask import request

from errors import ApiError

ROLE_DEALER = "Dealer"
ROLE_MANUFACTURER = "Manufacturer"
ROLE_LICENSING_ANALYST = "LicensingAnalyst"
ROLE_HEARING_CLERK = "HearingClerk"
ROLE_COMPLAINT_INVESTIGATOR = "ComplaintInvestigator"
ROLE_BOARD_ADMIN = "BoardAdmin"

ALL_ROLES = (
    ROLE_DEALER,
    ROLE_MANUFACTURER,
    ROLE_LICENSING_ANALYST,
    ROLE_HEARING_CLERK,
    ROLE_COMPLAINT_INVESTIGATOR,
    ROLE_BOARD_ADMIN,
)

ENTITY_BACKED_ROLES = (ROLE_DEALER, ROLE_MANUFACTURER)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_dealer(self):
        return self.role == ROLE_DEALER

    @property
    def is_manufacturer(self):
        return self.role == ROLE_MANUFACTURER


def authenticate():
    """Stage 1: both headers present, non-empty, and a declared role."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not one of the six declared roles")
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Stage 2: the endpoint's authorised-role list is exhaustive."""
    if caller.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s is not authorised for this endpoint" % caller.role)
    return caller


def guard(roles):
    """Authenticate and authorise in one step, returning the caller."""
    return require_roles(authenticate(), roles)


def require_owner(caller, owner_id):
    """Stage 3: an entity-backed caller may act only on its own record."""
    if caller.role not in ENTITY_BACKED_ROLES:
        return
    if owner_id is None or caller.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own the addressed resource")


def require_dealer_owner(caller, dealer_id):
    if caller.role == ROLE_DEALER and caller.user_id != dealer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own the addressed resource")


def require_manufacturer_owner(caller, manufacturer_id):
    if caller.role == ROLE_MANUFACTURER and caller.user_id != manufacturer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own the addressed resource")
