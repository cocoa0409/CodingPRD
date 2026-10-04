"""Caller-context (priority 1, headers) and role authorization (priority 2)."""
from flask import request

from constants import ALL_ROLES
from errors import api_err


def caller():
    """Priority 1 (headers): X-User-ID and X-User-Role must be present and the
    role must be a declared role."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ALL_ROLES:
        raise api_err(
            'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
            'X-User-ID and X-User-Role headers are required and X-User-Role must '
            'be one of the declared roles',
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2: caller's role must be listed for the endpoint."""
    if role not in allowed:
        raise api_err(
            'ERR_FORBIDDEN_ROLE',
            'Role {} is not authorized for this operation'.format(role),
        )


def not_owner(message):
    return api_err('ERR_NOT_RESOURCE_OWNER', message)
