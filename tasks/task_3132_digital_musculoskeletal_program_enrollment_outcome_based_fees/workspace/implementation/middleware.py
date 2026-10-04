"""Auth context extraction and RBAC enforcement (PRD §2.1, §2.11).

Priority 1: X-User-ID and X-User-Role must both be present and the role must be
one of the eight declared names -- otherwise
ERR_MISSING_OR_INVALID_CONTEXT_HEADER (400).
Priority 2: the named role must be permitted for the operation under the §1.7
matrix -- otherwise ERR_FORBIDDEN_ROLE (403).
"""

from flask import request

from db import ENTITY_ROLES, OPAQUE_ROLES, ROLES, STORE
from errors import ApiError, forbidden_role, missing_context, not_found

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


def context():
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise missing_context()
    return user_id.strip(), role.strip()


def require(allowed, operation, entity_lookup=True):
    """Return (user_id, role) after enforcing presence and permission."""
    user_id, role = context()
    if allowed and role not in allowed:
        raise forbidden_role(role, operation)
    if entity_lookup and role in ENTITY_ROLES:
        entity = ENTITY_ROLES[role]
        if STORE.get(entity, user_id) is None:
            raise not_found("%s %s" % (entity, user_id))
    return user_id, role


def body():
    """JSON request body, tolerating an empty one."""
    return request.get_json(silent=True) or {}



def query(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return value
