"""Auth middleware: header extraction, role registry and ownership checks.

Header names and role names are taken from the scaffold's auth validation rules
(validations[priority=1..2]) and PRD section 2.1: the two headers are
``X-User-ID`` and ``X-User-Role``.
"""

from flask import request

from errors import ApiError

# The eight operating roles of PRD section 2.1.  `ProductDesigner` appears as an
# authorized role on the product-plane endpoints of the PRD's endpoint table and
# the scaffold's endpoint table, so it is honoured as a recognized role name.
GIVING_PARTNER_COORDINATOR = "GivingPartnerCoordinator"
GIVING_PARTNER_ORG = "GivingPartnerOrg"
PROVISIONING_PARTNER = "ProvisioningPartner"
ALLOCATION_PLANNER = "AllocationPlanner"
FULFILLMENT_OPERATOR = "FulfillmentOperator"
CUSTOMER_SERVICE = "CustomerService"
MARKETING_MANAGER = "MarketingManager"
IMPACT_AUDITOR = "ImpactAuditor"
PRODUCT_DESIGNER = "ProductDesigner"

ROLES = {
    GIVING_PARTNER_COORDINATOR,
    GIVING_PARTNER_ORG,
    PROVISIONING_PARTNER,
    ALLOCATION_PLANNER,
    FULFILLMENT_OPERATOR,
    CUSTOMER_SERVICE,
    MARKETING_MANAGER,
    IMPACT_AUDITOR,
    PRODUCT_DESIGNER,
}

# Endpoints exempt from the authentication rung (validations[priority=1]
# applies_to: "all endpoints except POST /_clock/set_current_utc and
# POST /_seasons/roll").  The liveness probe sits outside the business surface
# too, so it is also answered without an auth context.
AUTH_EXEMPT = {
    ("POST", "/_clock/set_current_utc"),
    ("POST", "/_seasons/roll"),
    ("GET", "/_healthz"),
}

_ALL = sorted(ROLES)


def roles(*allowed):
    """Declare the roles permitted for a view function."""

    def decorate(fn):
        fn._allowed_roles = set(allowed)
        return fn

    return decorate


def all_roles(fn):
    fn._allowed_roles = set(_ALL)
    return fn


def acting_role():
    return request.headers.get("X-User-Role")


def acting_id():
    return request.headers.get("X-User-ID")


def authenticate():
    """Priority 1: both headers present and the role recognized."""
    role = acting_role()
    user_id = acting_id()
    if not role or not user_id:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT")
    if role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT")
    return role, user_id


def authorize(allowed):
    """Priority 2: the acting role is permitted for this operation."""
    role = acting_role()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return role


def require_own_partner(partner_id):
    """Ownership filter for the entity-backed GivingPartnerOrg role."""
    if acting_role() == GIVING_PARTNER_ORG and acting_id() != partner_id:
        raise ApiError("ERR_FORBIDDEN_ROLE")