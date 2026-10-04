"""Auth header extraction and role checking (validation priorities 1 and 2).

PRD §2.1: every authenticated request carries X-User-ID and X-User-Role; both
are mandatory, and either one missing, empty or naming an undeclared role is
ERR_UNAUTHENTICATED (401).  A well-formed pair claiming a role the operation
does not admit is ERR_UNAUTHORIZED (403).

Five roles are opaque operator identifiers that the service never resolves to
a persisted row.  The sixth, Anonymous, is likewise opaque.  Only the Engineer
role is entity-backed: X-User-ID is the acting Engineer's id, which is what
makes the ownership checks on assignment acceptance, quote amendment and
backorder cancellation personal (§2.1).
"""

from flask import request

from errors import ApiError, Err

ROLES = (
    "PlatformAdmin",
    "SalesEngineerOps",
    "Engineer",
    "SetupTechnician",
    "SupportAgent",
    "ServiceDepartment",
    "Anonymous",
)

# Endpoints exempt from the header requirement entirely (PRD §2.1).
ANONYMOUS_ROLES = ("Anonymous",)


def current_identity():
    """Priority 1: both headers present and the role declared."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(Err.UNAUTHENTICATED)
    return user_id, role


def authorize(role, allowed):
    """Priority 2: the acting role is listed for this operation."""
    if role not in allowed:
        raise ApiError(Err.UNAUTHORIZED)


def guard(allowed):
    """Both auth layers, in priority order; returns (user_id, role)."""
    user_id, role = current_identity()
    authorize(role, allowed)
    return user_id, role


def optional_guard(allowed):
    """For the header-exempt creation routes (PRD §2.1).

    Absent headers are admitted outright -- POST /products, POST
    /service-centers, POST /engineers and POST /customers are self-service.
    A caller that *does* present headers still has to present a usable pair
    and a role the operation admits.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role and not user_id:
        return None, "Anonymous"
    return guard(allowed)


def require_engineer_owner(user_id, role, resource, field="engineer_id"):
    """Engineer-backed ownership: only the Engineer role is checked.

    The five opaque operator roles never make an ownership decision, so they
    pass through untouched.
    """
    if role == "Engineer" and resource.get(field) != user_id:
        raise ApiError(Err.UNAUTHORIZED,
                       "The acting Engineer does not own the named resource.")