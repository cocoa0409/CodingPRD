"""Authentication and role authorization (PRD 2.1, validation priorities 1-2)."""
from flask import request

from db import STORE
from errors import raise_err

ALL_ROLES = ("WorkshopManager", "MasterCraftsman", "Apprentice", "ArtistLiaison", "Artist")

# Entity-backed roles: X-User-ID must resolve to an existing entity.
ENTITY_STORE_FOR_ROLE = {
    "MasterCraftsman": "craftsmen",
    "Apprentice": "apprentices",
    "Artist": "artists",
}


def authenticate(allowed_roles):
    """Validate headers, then role membership. Returns {"id", "role"}."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise_err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-ID / X-User-Role")
    store_name = ENTITY_STORE_FOR_ROLE.get(role)
    if store_name is not None and uid not in STORE[store_name]:
        raise_err("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to an existing %s" % role)
    if role not in allowed_roles:
        raise_err("ERR_UNAUTHORIZED_ROLE", "Role %s is not authorized for this endpoint" % role)
    return {"id": uid, "role": role}
