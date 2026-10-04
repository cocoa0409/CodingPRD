"""Auth header extraction, role checking and request helpers."""

from flask import request

import errors
from errors import ApiError

ROLES = {"PlatformAdmin", "KitchenLead", "Server", "ProgrammingCoordinator",
         "PreShowProducer", "Anonymous"}


class Principal(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_server(self):
        return self.role == "Server"


def authenticate():
    """Authentication then authorisation headers. Never touches any resource."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return Principal(user_id, role)


def authorize(principal, allowed_roles):
    if principal.role not in allowed_roles:
        raise ApiError(errors.ERR_UNAUTHORIZED_ROLE)
    return principal


def principal_for(allowed_roles):
    principal = authenticate()
    return authorize(principal, allowed_roles)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def raw_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def pagination():
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def page(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    return limit, offset, total, rows[offset:offset + limit], serializer


def require_id(data, field, error_id, http_status=None):
    value = data.get(field)
    if value is None:
        raise ApiError(error_id)
    return value


def get_int(data, field):
    value = data.get(field)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None