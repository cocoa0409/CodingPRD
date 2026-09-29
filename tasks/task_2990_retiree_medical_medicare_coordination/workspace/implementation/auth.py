"""Authentication, authorization and ownership (PRD 2.1, ladder steps 1-2)."""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, fail

ROLE_BENEFITS_ADMIN = "BenefitsAdmin"
ROLE_ELIGIBILITY_ANALYST = "EligibilityAnalyst"
ROLE_ENROLLMENT_COUNSELOR = "EnrollmentCounselor"
ROLE_HRA_ADMINISTRATOR = "HraAdministrator"
ROLE_BILLING_CLERK = "BillingClerk"
ROLE_ACTUARY = "Actuary"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_RETIREE = "Retiree"

DECLARED_ROLES = (
    ROLE_BENEFITS_ADMIN,
    ROLE_ELIGIBILITY_ANALYST,
    ROLE_ENROLLMENT_COUNSELOR,
    ROLE_HRA_ADMINISTRATOR,
    ROLE_BILLING_CLERK,
    ROLE_ACTUARY,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RETIREE,
)

ALL_ROLES = DECLARED_ROLES

# Every role except Retiree -- used by GET /retiree-benefits/retirees.
ALL_ROLES_EXCEPT_RETIREE = tuple(r for r in DECLARED_ROLES if r != ROLE_RETIREE)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_retiree(self):
        return self.role == ROLE_RETIREE


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def require_caller(allowed_roles):
    """Ladder 1 then ladder 2, in that exact order, on every endpoint."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")

    if user_id is None or user_id.strip() == "":
        fail(ERR_UNAUTHENTICATED, "X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        fail(ERR_UNAUTHENTICATED, "X-User-Role header is missing or empty.")
    if role not in DECLARED_ROLES:
        fail(ERR_UNAUTHENTICATED, "X-User-Role is not one of the eight declared roles.")

    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED)

    return Caller(user_id, role)


def require_ownership(caller, retiree_id):
    """PRD 2.1: for the entity-backed Retiree role, X-User-ID is the Retiree.id;
    an ownership mismatch is an authorization failure."""
    if caller.is_retiree and caller.user_id != retiree_id:
        fail(ERR_UNAUTHORIZED, "The acting retiree does not own the target resource.")
