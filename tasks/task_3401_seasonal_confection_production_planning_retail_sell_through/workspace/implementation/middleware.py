"""Authentication and role authorization — PRD 2.1.

Every request carries X-User-ID and X-User-Role. Missing headers or an
undeclared role -> ERR_UNAUTHENTICATED (401). A declared role not authorized
for the endpoint -> ERR_UNAUTHORIZED (403).

When the role is Retailer, X-User-ID is the id of the acting RetailerAccount;
ownership checks compare a resource's retailer_id to X-User-ID. For the other
five roles X-User-ID is an opaque operator identifier.
"""

from collections import namedtuple

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PRODUCTION_PLANNER = "ProductionPlanner"
ROLE_RETAILER = "Retailer"
ROLE_CATEGORY_MANAGER = "CategoryManager"
ROLE_LOGISTICS_COORDINATOR = "LogisticsCoordinator"
ROLE_CLAIMS_ADJUSTER = "ClaimsAdjuster"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PRODUCTION_PLANNER,
    ROLE_RETAILER,
    ROLE_CATEGORY_MANAGER,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_CLAIMS_ADJUSTER,
)

Actor = namedtuple("Actor", ["user_id", "role"])


def authorize(*allowed_roles):
    """Validate headers (401) and endpoint role membership (403).

    Called inside each handler after syntactic body validation, honouring
    PRD 2.8: syntactic request validation comes before all numbered
    priorities, and authentication is priority 1, authorization priority 2.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(401, ERR_UNAUTHENTICATED,
                       "X-User-ID and X-User-Role headers are required and the role must be declared")
    if role not in allowed_roles:
        raise ApiError(403, ERR_UNAUTHORIZED,
                       "role %s is not authorized for this endpoint" % role)
    return Actor(user_id, role)
