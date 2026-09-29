"""Identity, role and scope enforcement (PRD 2.1, band 1 of PRD 2.9)."""
from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
PARTNER_MANAGER = "PartnerManager"
MERCHANT = "Merchant"
EMPLOYER_ADMIN = "EmployerAdmin"
EMPLOYEE = "Employee"

ALL_ROLES = [PLATFORM_ADMIN, PARTNER_MANAGER, MERCHANT, EMPLOYER_ADMIN, EMPLOYEE]

# PRD 2.1: PlatformAdmin and PartnerManager identifiers are opaque staff ids and
# are never resolved to a row, so no ownership check ever applies to them.
OPAQUE_ROLES = (PLATFORM_ADMIN, PARTNER_MANAGER)


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_merchant(self):
        return self.role == MERCHANT

    @property
    def is_employer_admin(self):
        return self.role == EMPLOYER_ADMIN

    @property
    def is_employee(self):
        return self.role == EMPLOYEE

    @property
    def is_opaque(self):
        return self.role in OPAQUE_ROLES


def require(*allowed_roles):
    """Band 1: identity first, then role. Returns the acting Principal."""
    user_id = request.headers.get(USER_ID_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_IDENTITY_REQUIRED", "X-User-ID header is required.")
    role = request.headers.get(USER_ROLE_HEADER)
    if role is None:
        role = ""
    role = role.strip()
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role '%s' is not authorized for this operation." % role,
        )
    return Principal(str(user_id).strip(), role)


def deny_scope(message="The target row belongs to a different principal."):
    raise ApiError("ERR_SCOPE_VIOLATION", message)


def check_merchant_scope(principal, merchant_id):
    """Merchant callers may only reach rows carrying their own merchant_id."""
    if principal.is_merchant and merchant_id != principal.user_id:
        deny_scope()


def check_employer_scope(principal, employer_id):
    if principal.is_employer_admin and employer_id != principal.user_id:
        deny_scope()


def check_membership_scope(principal, membership_id):
    if principal.is_employee and membership_id != principal.user_id:
        deny_scope()
