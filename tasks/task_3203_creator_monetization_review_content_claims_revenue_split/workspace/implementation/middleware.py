"""Authentication header extraction and role checking (PRD section 2.1).

Two headers are read: `X-User-ID`, the acting principal, and `X-User-Role`, the
capacity in which it acts.
"""

from flask import request

from errors import ApiError, ERRORS

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"

DECLARED_ROLES = {
    "Anonymous",
    "Creator",
    "MonetizationReviewer",
    "Reviewer",
    "RightsHolder",
    "Moderator",
    "PlatformAdmin",
    "Any",
}

# Roles whose X-User-ID names a persisted row rather than an opaque operator.
ENTITY_BACKED_ROLES = {"Creator": "Channel", "RightsHolder": "ReferenceFile"}


def current_principal():
    role = request.headers.get(ROLE_HEADER)
    if role is None or role not in DECLARED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", ERRORS["ERR_UNAUTHENTICATED"][0])
    return role, request.headers.get(USER_HEADER)


def forbidden(message=None):
    raise ApiError("ERR_FORBIDDEN_ROLE", ERRORS["ERR_FORBIDDEN_ROLE"][0], message)


def require_role(*allowed):
    """Validate the declared role against an endpoint's authorized role set.

    `Any` is the read-only umbrella: every declared role -- including the
    `Anonymous` role, which PRD section 2.1 explicitly admits to public listings
    -- may read listings and single resources.
    """
    role, user_id = current_principal()
    if "Any" in allowed:
        return role, user_id
    if role not in allowed:
        forbidden()
    return role, user_id


def require_any_authenticated():
    return require_role("Any")


def require_creator_owns(channel_id):
    """An entity-backed Creator may act only on its own channel."""
    role, user_id = current_principal()
    if role == "Creator" and user_id != channel_id:
        forbidden("A creator may act only on its own channel.")


def require_rights_holder_owns(claim):
    """An entity-backed RightsHolder may act only on claims from its reference."""
    role, user_id = current_principal()
    if role == "RightsHolder" and claim.get("reference_file_id") != user_id:
        forbidden("A rights holder may act only on claims from its own reference file.")