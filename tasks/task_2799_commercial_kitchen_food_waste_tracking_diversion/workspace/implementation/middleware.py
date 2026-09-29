"""Authentication, authorization, identity resolution and scoping (PRD 2.1, 2.8)."""
from flask import request

from db import db
from errors import fail

KITCHEN_STAFF = "KitchenStaff"
SHIFT_LEAD = "ShiftLead"
SITE_MANAGER = "SiteSustainabilityManager"
HAULER_OPERATOR = "HaulerOperator"
CORPORATE_LEAD = "CorporateSustainabilityLead"
PLATFORM_ADMIN = "PlatformAdmin"

ROLES = (
    KITCHEN_STAFF,
    SHIFT_LEAD,
    SITE_MANAGER,
    HAULER_OPERATOR,
    CORPORATE_LEAD,
    PLATFORM_ADMIN,
)

# Every role that may read the operational record.
ALL_READERS = (
    KITCHEN_STAFF,
    SHIFT_LEAD,
    SITE_MANAGER,
    CORPORATE_LEAD,
    PLATFORM_ADMIN,
)

# Reads that a hauler operator may also perform.
HAULER_READERS = ALL_READERS + (HAULER_OPERATOR,)

ANY_ROLE = "*"


class Caller(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_site_manager(self):
        return self.role == SITE_MANAGER

    @property
    def is_hauler_operator(self):
        return self.role == HAULER_OPERATOR


def authenticate(allowed_roles):
    """Steps 1-3 of the validation order."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # Step 1: the role header must be present and name one of the six roles.
    if role is None or role.strip() == "" or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role must name one of the six roles.")

    if allowed_roles == ANY_ROLE:
        return Caller(role, user_id if user_id else None)

    # Step 1 (continued): role-restricted endpoints also require an identity.
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required on this endpoint.")

    # Step 2: the role must be admitted by the endpoint.
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)

    # Step 3: entity-backed identities must name an existing row.
    if role == SITE_MANAGER and user_id not in db.sites:
        fail("ERR_IDENTITY_NOT_RECOGNIZED",
             "X-User-ID does not name an existing site.")
    if role == HAULER_OPERATOR and user_id not in db.haulers:
        fail("ERR_IDENTITY_NOT_RECOGNIZED",
             "X-User-ID does not name an existing hauler.")

    return Caller(role, user_id)


def require_site_scope(caller, site_id):
    """Step 8: a SiteSustainabilityManager acts only within its own site."""
    if caller.is_site_manager and site_id != caller.user_id:
        fail("ERR_SITE_SCOPE_VIOLATION",
             "The caller may only act on rows of its own site.")


def require_hauler_scope(caller, hauler_id):
    """Step 9: a HaulerOperator acts only within its own hauler."""
    if caller.is_hauler_operator and hauler_id != caller.user_id:
        fail("ERR_HAULER_SCOPE_VIOLATION",
             "The caller may only act on rows of its own hauler.")
