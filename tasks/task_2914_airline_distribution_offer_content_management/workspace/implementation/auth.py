"""Authentication / authorization middleware (PRD 2.1, 2.10 steps 1-2)."""
from flask import request

from errors import ApiError

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PRICING_ANALYST = "PricingAnalyst"
ROLE_DISTRIBUTION_MANAGER = "DistributionManager"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_AGENCY = "Agency"
ROLE_TECHNOLOGY_PARTNER = "TechnologyPartner"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PRICING_ANALYST,
    ROLE_DISTRIBUTION_MANAGER,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_AGENCY,
    ROLE_TECHNOLOGY_PARTNER,
)

# The two entity-backed roles: X-User-ID is the acting DistributionPartner id.
ENTITY_BACKED_ROLES = (ROLE_AGENCY, ROLE_TECHNOLOGY_PARTNER)

READ_ALL_ROLES = ALL_ROLES


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED_ROLES

    def require_owner(self, partner_id):
        """PRD 2.1: entity-backed roles may only touch their own resources."""
        if not self.entity_backed:
            return
        if partner_id is None:
            return
        if partner_id != self.user_id:
            raise ApiError(
                "ERR_UNAUTHORIZED",
                "The acting principal does not own the target resource.",
            )


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role does not name a declared role.")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not call this endpoint." % role)
    return Actor(user_id, role)
