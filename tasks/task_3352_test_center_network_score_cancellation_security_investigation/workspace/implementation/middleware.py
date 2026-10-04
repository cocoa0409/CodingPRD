"""Authentication and endpoint role authorization (PRD 2.1, 2.6 steps 1-2).

Every request carries X-User-ID and X-User-Role. Missing/malformed headers or
an undeclared role name -> ERR_UNAUTHENTICATED (401). A declared role not
listed for the endpoint -> ERR_UNAUTHORIZED (403).
"""

from functools import wraps

from flask import g, request

from errors import ApiError

DECLARED_ROLES = {
    'ProgramAdmin',
    'Auditor',
    'CenterManager',
    'Proctor',
    'Examinee',
    'ScoreAnalyst',
}


def require_roles(allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get('X-User-ID')
            role = request.headers.get('X-User-Role')
            if not user_id or not isinstance(user_id, str) or not role or role not in DECLARED_ROLES:
                raise ApiError('ERR_UNAUTHENTICATED', 401,
                               'Missing or malformed X-User-ID / X-User-Role headers')
            if role not in allowed:
                raise ApiError('ERR_UNAUTHORIZED', 403,
                               'Role {} is not permitted on this endpoint'.format(role))
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
