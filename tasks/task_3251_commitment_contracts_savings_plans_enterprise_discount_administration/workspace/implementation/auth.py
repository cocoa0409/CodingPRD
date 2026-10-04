from flask import request
from store import ApiError
from response import ROLES


def require_auth(*allowed_roles):
    """Priority 1-2 auth. Returns (user_id, role). allowed_roles empty => any declared role."""
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'missing or unknown X-User-ID / X-User-Role')
    if allowed_roles and role not in allowed_roles:
        raise ApiError('ERR_FORBIDDEN', 403, 'role not permitted for this endpoint')
    return user_id, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'request body must be a JSON object')
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'missing or invalid field: ' + field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'invalid field: ' + field)
    return v


def req_int(data, field, min_value=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'missing or invalid integer field: ' + field)
    if min_value is not None and v < min_value:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'field ' + field + ' below minimum')
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'invalid boolean field: ' + field)
    return v


def req_rate(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'missing or invalid rate field: ' + field)
    if not (0 <= v < 1):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'rate must be in [0, 1)')
    return v
