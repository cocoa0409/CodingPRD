"""Identity, role and segregation-of-duties gates (validation ladder ranks 1-4)."""

from flask import request

import core
from constants import ENTITY_BACKED_ROLES, ROLES
from errors import fail


def authenticate(allowed_roles):
    """Ranks 1-3. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or not str(role).strip() or user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    user_id = str(user_id).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    backing = ENTITY_BACKED_ROLES.get(role)
    if backing is not None and core.get(backing, user_id) is None:
        fail("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to an existing %s." % backing)
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return role, user_id


def check_sod(actor_user_id, recorded_user_id):
    """Rank 4 - the acting user may not decide a record it filed or reported."""
    if recorded_user_id and actor_user_id == recorded_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
