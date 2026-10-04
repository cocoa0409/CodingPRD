"""Auth header extraction and role gating (validations priority 1 and 2)."""

from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    fail,
)

ROLES = ("PlatformAdmin", "TrustReviewer", "Employer", "JobSeeker")
ENTITY_BACKED = {"Employer": "Employer", "JobSeeker": "JobSeeker"}


def actor():
    """Parse X-User-ID / X-User-Role; malformed or unknown role is a 400."""
    from flask import request

    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
             "X-User-ID and X-User-Role headers are required.")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role not in ROLES:
        fail(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
             "X-User-ID and X-User-Role must carry a well-formed identity and one of "
             "PlatformAdmin, TrustReviewer, Employer, JobSeeker.")
    return user_id, role


def require_role(actor_id, role, allowed):
    """Tier-2 role gate.  ``allowed`` lists the roles authorized for the operation."""
    if role not in allowed:
        fail(ERR_INSUFFICIENT_PERMISSIONS,
             "Role %s is not permitted for this operation." % role)
    return True


def is_entity_backed(role):
    return role in ENTITY_BACKED


def require_ownership(actor_id, role, target_kind, owner_kind, owner_id):
    """Tier-2 ownership gate for the two entity-backed roles.

    ``target_kind``/``owner_kind`` name the entity types so the message reads well.
    """
    if not is_entity_backed(role):
        return True
    if ENTITY_BACKED[role] != owner_kind:
        return True
    if str(actor_id) != str(owner_id):
        fail(ERR_INSUFFICIENT_PERMISSIONS,
             "The %s caller does not own the target %s." % (role, target_kind))
    return True


def is_own_identity(actor_id, role, owner_kind, owner_id):
    """True when the caller is that entity (no a-priori gate) — used for reads."""
    if is_entity_backed(role) and ENTITY_BACKED[role] == owner_kind:
        return str(actor_id) == str(owner_id)
    return False