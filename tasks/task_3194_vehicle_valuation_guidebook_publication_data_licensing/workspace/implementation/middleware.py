"""Auth middleware: X-User-Role / X-User-ID per PRD §2.1."""
from __future__ import annotations

from typing import Optional, Tuple

from flask import request

from errors import unauthenticated, unauthorized, ApiError


ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")

# Roles whose X-User-ID names a persisted entity (entity-backed). For opaque
# roles (ValuationAdmin, DataOps) the X-User-ID is required only as a
# principal identifier; it is not matched to any stored entity.
ENTITY_BACKED_ROLES = ("DealerPartner", "Consumer", "Licensee")


def get_auth() -> Tuple[str, str]:
    """Return (role, user_id). Raises ApiError(ERR_UNAUTHENTICATED) on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or role not in ROLES:
        raise unauthenticated("X-User-Role header missing or unknown")

    # Per PRD §2.1: X-User-ID is required for entity-backed roles. For opaque
    # roles we also require it to be present (the header contract is two
    # mandatory headers), but we do not cross-check against entities.
    if not user_id:
        raise unauthenticated("X-User-ID header missing")

    return role, user_id


def require_roles(*allowed: str) -> Tuple[str, str]:
    """Authenticate then authorize against the allowed role list."""
    role, user_id = get_auth()
    if role not in allowed:
        raise unauthorized(f"Role {role} not permitted on this endpoint")
    return role, user_id
