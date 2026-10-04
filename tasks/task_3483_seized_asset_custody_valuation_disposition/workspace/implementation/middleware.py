"""Authentication and role authorization (PRD §2.1, pipeline tiers 1-2).

Tier 1: X-User-Role and X-User-ID present and the role is declared
        (ERR_UNAUTHENTICATED, 401).
Tier 2: caller's role is in the endpoint's role list (ERR_FORBIDDEN, 403).
        Identity-pinned rules (Claimant petitioner_ref equality) also fire at
        this tier; the two segregation-of-duties pairs deliberately do NOT
        (they are tier 7).
"""

from flask import request

import errors
from constants import (
    ROLES,
    BUSINESS_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
)


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed_roles):
    """Authenticate, then enforce the endpoint's role list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise errors.forbidden()
    return user_id, role


def require_business_role():
    """Read endpoints: shared by every business role (not SystemOperator)."""
    return require_roles(*BUSINESS_ROLES)
