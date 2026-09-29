"""Authentication, role recognition, role permission and laboratory identity —
ladder priorities 1 through 4 (PRD sections 2.1 and 2.7).
"""

from flask import request

import constants as C
from db import store
from errors import ApiError


def authenticate(allowed_roles, laboratory_identity=False):
    """Returns (user_id, role).

    Priority 1: both headers must be present and non-blank.
    Priority 2: the role must be one of the seven recognised roles.
    Priority 3: the role must be permitted on this endpoint.
    Priority 4: a LaboratoryManager's X-User-ID must name an existing laboratory
                (only on the four laboratory-scoped endpoints).
    """
    user_id = request.headers.get(C.HEADER_USER_ID)
    role = request.headers.get(C.HEADER_USER_ROLE)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in C.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not C.ANY_ROLE and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if laboratory_identity and role == "LaboratoryManager":
        if user_id not in store.laboratories:
            raise ApiError("ERR_LABORATORY_NOT_OWNED")
    return user_id, role
