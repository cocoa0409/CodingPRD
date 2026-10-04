"""Auth header extraction and role checking (PRD §2.1, §2.8 priorities 1-3)."""

from flask import request

from errors import raise_err

ROLES = {
    "Anonymous",
    "CarrierAdmin",
    "RatingManager",
    "UnderwritingReviewer",
    "Agent",
    "Consumer",
    "ComparativeRater",
    "System",
}

# Roles whose X-User-ID equals an entity id (§2.1). Opaque roles carry an
# arbitrary operator id that is never compared against entity ids.
ENTITY_BACKED = {"Agent", "Consumer", "ComparativeRater"}


def get_auth():
    """Validate headers; return (user_id, role).

    Priority 1 (§2.8): missing/empty header or unknown role -> 400.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present, non-empty, and name a declared role",
        )
    return user_id, role


def require_role(*allowed):
    """Priority 2: role must be listed in the endpoint's roles."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_err(
            "ERR_FORBIDDEN_FOR_ROLE",
            f"Role {role} is not authorized for this endpoint",
        )
    return user_id, role


def check_ownership(user_id, role, expected_id):
    """Priority 3: entity-backed callers must match the owning FK.

    Opaque roles (CarrierAdmin, RatingManager, UnderwritingReviewer, System,
    Anonymous) are never compared against entity ids.
    """
    if role in ENTITY_BACKED and expected_id is not None and user_id != expected_id:
        raise_err(
            "ERR_OWNERSHIP_MISMATCH",
            f"{role} caller does not own the target resource",
        )
