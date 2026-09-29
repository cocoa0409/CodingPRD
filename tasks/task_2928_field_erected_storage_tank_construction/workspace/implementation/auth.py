"""Authentication, RBAC and the welder identity match (PRD 2.1, 2.10)."""

from functools import wraps

from flask import g, request

import errors
from errors import ApiError
from util import LOCK

PROJECT_ENGINEER = "ProjectEngineer"
CIVIL_CONTRACTOR = "CivilContractor"
ERECTION_SUPERINTENDENT = "ErectionSuperintendent"
WELDER = "Welder"
QC_INSPECTOR = "QcInspector"
AUTHORIZED_INSPECTOR = "AuthorizedInspector"

ALL_ROLES = (
    PROJECT_ENGINEER,
    CIVIL_CONTRACTOR,
    ERECTION_SUPERINTENDENT,
    WELDER,
    QC_INSPECTOR,
    AUTHORIZED_INSPECTOR,
)


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    # PRD 2.1: "A blank string is treated exactly as if the header had not been
    # sent at all."
    return value or None


def body_of(silent=True):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def endpoint(roles):
    """Order of rejection steps 1 and 2 (PRD 2.10) plus the global lock."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                user_id = _header("X-User-ID")
                role = _header("X-User-Role")
                if user_id is None or role is None:
                    raise ApiError(errors.ERR_UNAUTHENTICATED, 401)
                if role not in ALL_ROLES or role not in roles:
                    raise ApiError(errors.ERR_FORBIDDEN_ROLE, 403)
                g.user_id = user_id
                g.role = role
                g.body = body_of()
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_user():
    return g.user_id
