"""Auth middleware (PRD 2.1): header validation, role authorization, ownership.

Validation pipeline stages 1-3:
  1. header presence + role validity  -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
  2. role in endpoint roles           -> ERR_FORBIDDEN_FOR_ROLE
  3. distributor ownership scoping    -> ERR_NOT_RESOURCE_OWNER
"""
from flask import request

from constants import (
    HEADER_USER_ID, HEADER_USER_ROLE, ALL_ROLES, ROLE_DISTRIBUTOR,
)
from errors import (
    ApiError, ERR_MISSING_CONTEXT, ERR_FORBIDDEN_ROLE, ERR_NOT_OWNER, raise_err,
)


def caller():
    """Stage 1: both headers present, non-empty, role declared."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ALL_ROLES:
        raise_err(
            ERR_MISSING_CONTEXT,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return user_id, role


def require_role(role, allowed):
    """Stage 2: role must be in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, f"Role {role} is not authorized for this operation")


def require_owner(user_id, owner_id):
    """Stage 3: a Distributor caller may only address its own resources."""
    if owner_id is not None and user_id != owner_id:
        raise_err(ERR_NOT_OWNER, "Distributor may only act on its own resources")


def require_path_distributor(user_id, role, path_distributor_id):
    """Ownership for /distributors/{id}/... paths (checked before existence)."""
    if role == ROLE_DISTRIBUTOR and user_id != path_distributor_id:
        raise_err(ERR_NOT_OWNER, "Distributor may only act on its own resources")


def check_resource_owner(user_id, role, owner_id):
    """Ownership for distributor-owned resources addressed by their own id."""
    if role == ROLE_DISTRIBUTOR:
        require_owner(user_id, owner_id)
