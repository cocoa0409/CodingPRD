"""Auth header extraction and role/ownership enforcement (§2.1, validations 1-2)."""
from flask import request

import constants as C
from errors import fail

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


def authenticate():
    """Priority 1: headers present and the role is one of the five declared roles."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(ID_HEADER)
    if not role or not user_id or role not in C.ROLES:
        fail("ERR_UNAUTHENTICATED")
    return role, user_id


def authorize(role, allowed_roles):
    """Priority 2: the acting role is permitted for this operation."""
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")


def enforce_entity_ownership(role, user_id, owner_id):
    """An entity-backed role may only act on resources whose owning FK equals X-User-ID."""
    if role in C.ENTITY_BACKED_ROLES:
        if owner_id is None or owner_id != user_id:
            fail("ERR_UNAUTHORIZED")


def guard(allowed_roles, owner_getter=None):
    """Authenticate + authorize + (optionally) entity-backed ownership."""
    role, user_id = authenticate()
    authorize(role, allowed_roles)
    if owner_getter is not None:
        enforce_entity_ownership(role, user_id, owner_getter())
    return role, user_id