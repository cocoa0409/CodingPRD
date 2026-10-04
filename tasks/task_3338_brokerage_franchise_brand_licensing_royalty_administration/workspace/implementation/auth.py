"""Authentication (X-User-Role / X-User-ID) and per-endpoint role checks."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = {'FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor'}
# FranchiseeAdmin is entity_backed:Brokerage — X-User-ID is the brokerage id.
ENTITY_BACKED = {'FranchiseeAdmin'}

# Value stored on GCIReport.reported_by_role per PRD 3.4.
REPORTED_BY_ROLE = {
    'FranchiseeAdmin': 'FRANCHISEE_ADMIN',
    'FranchisorOps': 'FRANCHISOR_OPS',
}


def authenticate():
    role = request.headers.get('X-User-Role')
    if role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'missing or unrecognized X-User-Role header')
    uid = request.headers.get('X-User-ID')
    if role in ENTITY_BACKED and not uid:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'X-User-ID header is required for entity-backed roles')
    return role, uid


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, uid = authenticate()
            if role not in allowed:
                raise ApiError('ERR_UNAUTHORIZED_ROLE', 403,
                               'role is not permitted to call this endpoint')
            g.role = role
            g.uid = uid
            return fn(*args, **kwargs)
        return wrapper
    return deco


def forbidden_ownership():
    return ApiError('ERR_FORBIDDEN_OWNERSHIP', 403,
                    "caller does not own the target resource's brokerage scope")
